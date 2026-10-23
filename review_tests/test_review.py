"""Offline review/approval/word-alignment integration; no real notification or model calls."""
import contextlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

import test_workflow as fixture
worker, report, review, ingestion, speakers = fixture.worker, fixture.report, fixture.review, fixture.ingestion, fixture.speakers
import meeting_notifications as notifications


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(worker, 'ROOT', self.root))
        self.stack.enter_context(patch.object(worker, 'DB', self.root/'jobs.sqlite3'))
        self.stack.enter_context(patch.object(worker, 'API_KEY', 'x'*40))
        worker.init()
        self.job = worker.create_session('alice', 'meeting')
        self.folder = self.root/('processed-test_'+self.job['id'])
        self.folder.mkdir()
        report.save(self.folder/'meeting_metadata.json', dict(fixture.BASE))
        report.save(self.folder/'transcript.json', {'segments': [
            {'start':0, 'end':1, 'text':'There is no role document.', 'speaker':'SPEAKER_00', 'speaker_status':'assigned'},
            {'start':1, 'end':2, 'text':'I lived there until 27.', 'speaker':'SPEAKER_01', 'speaker_status':'assigned'}]})
        report.atomic(self.folder/'report.md', '# Draft\n\nThere is no role document.\n')
        _, _, segments = report.load_source(self.folder/'transcript.json')
        report.atomic(self.folder/'transcript.md', report.transcript_md(segments))
        worker.update(self.job['id'], state='completed', folder=str(self.folder), filename='test.wav')
        self.job = worker.get_job(self.job['id'])
        review.ensure(self.root, self.job)

    def action(self, action, revision=1, **kw):
        return review.act(self.root, self.job['id'], 'alice', dict(action=action, revision=revision, **kw))

    def test_approval_exact_revision_hash_and_replacement(self):
        self.assertIsNone(ingestion.document(self.folder,self.root,True))
        with self.assertRaises(review.Conflict):
            review.act(self.root,self.job['id'],'bob',{'action':'approve','revision':1})
        self.action('approve')
        first = ingestion.document(self.folder,self.root)
        self.assertIn(b'no role document', first['raw'])
        result = self.action('replace', content='User reviewed replacement.')
        self.assertEqual(result['revision'],2)
        # Current edited draft requires new approval; previous approved version remains eligible unchanged.
        self.assertEqual(ingestion.document(self.folder,self.root)['sha256'],first['sha256'])
        with self.assertRaises(review.Conflict): self.action('approve',revision=1)
        self.action('approve',revision=2)
        second = ingestion.document(self.folder,self.root)
        self.assertNotEqual(second['sha256'], first['sha256'])
        self.assertEqual(ingestion.document(self.folder,self.root,approved_revision=1)['sha256'],first['sha256'])
        path = Path(second['source'])
        path.write_text('tampered',encoding='utf-8')
        with self.assertRaises(ingestion.IngestionError): ingestion.document(self.folder,self.root)
        with self.assertRaises(review.Conflict): self.action('approve',revision=2)

    def test_feedback_corrections_background_recovery(self):
        self.action('correct',segment='S000002',content='I lived there until age 27.',request_key='correction1')
        self.assertTrue(ingestion.worker_busy(self.root))
        with self.assertRaises(review.Conflict): self.action('approve')
        captured=[]
        def generate(payload,archive):
            captured.append(payload)
            return '# Corrected draft\nLived there until age 27.'
        self.assertTrue(review.process_next(self.root,generate))
        self.assertEqual(captured[0]['transcript']['segments'][1]['text'],'I lived there until age 27.')
        current = review.view(self.root,self.job['id'],'alice')
        self.assertEqual(current['revision'],2)
        self.assertIn('age 27',current['transcript'])
        self.assertIsNone(ingestion.document(self.folder,self.root))
        self.action('speakers',revision=2,mapping={'SPEAKER_00':'Domenico'},request_key='map1')
        review.process_next(self.root,lambda payload,path:'Domenico reported that the role document is missing.')
        current = review.view(self.root,self.job['id'],'alice')
        self.assertIn('Domenico',current['transcript'])
        self.assertIn('Domenico',current['speaker_mapping'].values())
        self.action('speaker',revision=3,segment='S000002',content='Jan Willem',request_key='voice1')
        review.process_next(self.root,lambda payload,path:'Domenico and Jan Willem discussed their roles.')
        self.assertIn('Jan Willem',review.view(self.root,self.job['id'],'alice')['transcript'])
        self.action('feedback',revision=4,feedback='Keep negation; do not invent documentation.',request_key='feedback1')
        with review.connection(self.root) as c:
            c.execute("UPDATE tasks SET status='running' WHERE status='queued'")
        review.recover(self.root)
        self.assertTrue(review.process_next(self.root,lambda payload,path:(_ for _ in ()).throw(ValueError('fake'))))
        current=review.view(self.root,self.job['id'],'alice')
        self.assertFalse(current['pending'])
        self.assertIsNotNone(current['error'])
        self.assertEqual(current['revision'],4)
        self.assertFalse(ingestion.worker_busy(self.root))
        self.action('retry',revision=4)
        review.process_next(self.root,lambda payload,path:'Retried with saved corrections: no document exists.')
        self.assertEqual(review.view(self.root,self.job['id'],'alice')['revision'],5)

    def test_word_level_alignment_retains_second_voice(self):
        source = [{'start':0,'end':3,'text':' Hello yes okay', 'words':[
            {'start':0,'end':1,'word':' Hello','probability':0.99},
            {'start':1,'end':1.3,'word':' yes','probability':0.99},
            {'start':1.3,'end':3,'word':' okay','probability':0.2}]}]
        raw=[{'start':0,'end':3,'speaker':'SPEAKER_00'},{'start':1,'end':1.3,'speaker':'SPEAKER_01'}]
        exclusive=[{'start':0,'end':1,'speaker':'SPEAKER_00'},raw[1],{'start':1.3,'end':3,'speaker':'SPEAKER_00'}]
        result=speakers.align_words(source,raw,exclusive)
        self.assertEqual({s['speaker'] for s in result},{'SPEAKER_00','SPEAKER_01'})
        self.assertEqual(''.join(s['text'] for s in result),source[0]['text'])
        self.assertEqual(result[1]['speaker_status'],'estimated_overlap')
        self.assertTrue(result[-1]['asr_uncertain'])
        self.assertNotIn('speaker',source[0])

    def test_review_http_auth_and_exact_approval(self):
        server=worker.ThreadingHTTPServer(('127.0.0.1',0),worker.Handler)
        server.worker_thread=threading.current_thread()
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            def call(method, owner, body=None, auth=True):
                conn=http.client.HTTPConnection(*server.server_address,timeout=5)
                headers={'X-Owner-Id':owner,'Content-Type':'application/json'}
                if auth: headers['Authorization']='Bearer '+'x'*40
                conn.request(method,'/v1/sessions/'+self.job['id']+'/review',json.dumps(body) if body else None,headers)
                response=conn.getresponse();data=json.loads(response.read());conn.close()
                return response.status,data
            self.assertEqual(call('GET','alice',auth=False)[0],401)
            self.assertEqual(call('GET','bob')[0],404)
            self.assertEqual(call('GET','alice')[1]['revision'],1)
            self.assertEqual(call('POST','alice',{'action':'approve','revision':99})[0],409)
            self.assertIsNone(ingestion.document(self.folder,self.root))
            self.assertEqual(call('POST','alice',{'action':'approve','revision':1})[0],200)
            self.assertIsNotNone(ingestion.document(self.folder,self.root))
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_claim_checker_and_no_invented_year(self):
        client=types.SimpleNamespace(args=types.SimpleNamespace(context=4096,output_tokens=512,token_safety=384),
                                     archive=self.folder,generate=lambda *a,**kw:{'supported':False})
        self.assertFalse(report.verify_claim(client,'A document outlines the role.',['There is no role document.']))
        self.assertTrue((self.folder/'omitted_claims.json').is_file())
        sources={'S000001':{'text':'I lived there until 27.'}}
        fact={'kind':'topic','topic':'Background','text':'Lived there until 2027.',
              'evidence':[{'id':'S000001','quote':'I lived there until 27.'}], 'owner':None,'deadline':None,'interpretation':None}
        with self.assertRaises(report.ReportError):
            report.validate({'facts':[fact]},sources,{'S000001':['I lived there until 27.']})

    def test_notification_binding_and_deduplication(self):
        home=self.root/'monitor';home.mkdir()
        (home/'meeting-notifications.json').write_text(json.dumps({'enabled':True,'owner_chats':{'alice':123}}))
        (home/'telegram-token.txt').write_text('not-a-real-token')
        (home/'telegram_notify.py').write_text("calls=[]\ndef read_token(path):return 'fake'\ndef api(*a,**kw):return {'message_id':1}\n")
        review.notice(self.root,'done','alice',self.job['id'],'Draft ready')
        with patch.dict(os.environ,{'MEETING_MONITOR_HOME':str(home)}):
            self.assertTrue(notifications.deliver_next(self.root))
            self.assertFalse(notifications.deliver_next(self.root))

        with review.connection(self.root) as c:
            self.assertEqual(c.execute('SELECT status FROM notices').fetchone()[0],'sent')
        # No binding for another owner: never send that owner's event to Alice.
        review.notice(self.root,'other','bob','b'*32,'Draft ready')
        with patch.dict(os.environ,{'MEETING_MONITOR_HOME':str(home)}):
            self.assertFalse(notifications.deliver_next(self.root))

    def test_authoritative_replacement_and_feedback_history_persist(self):
        self.action('replace',content='There was NO role documentation. Age 27, not year 2027.')
        self.action('feedback',revision=2,feedback='Keep these corrections and shorten.',request_key='f1')
        review.process_next(self.root,lambda payload,path:'No role documentation; age 27.')
        self.action('feedback',revision=3,feedback='Use two concise paragraphs.',request_key='f2')
        captured=[]
        def generate(payload,path):
            captured.append(payload)
            return 'No role documentation; age 27.'
        review.process_next(self.root,generate)
        self.assertIn('NO role documentation',captured[0]['authoritative_recap'])
        self.assertIn('Keep these corrections and shorten.',captured[0]['feedback_history'])

    def test_revision_generator_uses_saved_corrections(self):
        import meeting_revision
        captured=[]
        class Client:
            def __init__(self,args,archive):pass
            def discover(self):pass
            def generate(self,prompt,*a,**kw):
                captured.append(prompt)
                return {'recap':'The user confirmed that role documentation is absent.'}
        payload={'content':'Old draft','feedback':'Do not reverse negation.',
                 'feedback_history':['There is no document.'], 'authoritative_recap':'No document exists.',
                 'metadata':{'report_language':'English'},'transcript':{'segments':[{'text':'No document exists.'}]}}
        with patch.object(report,'Ollama',Client):
            result=meeting_revision.generate(payload,self.folder)
        self.assertIn('absent',result)
        self.assertIn('There is no document.',captured[0])
        self.assertIn('user_reviewed_recap_overrides_noisy_ASR',captured[0])



class FakeClient:
    def __init__(self):
        self.storage={};self.members={};self.uploads=0;self.fail_wait=False
    def version(self): pass
    def request(self,method,path,obj=None):return {'id':'kb','write_access':True,'name':'Test'}
    def files(self,kb):return list(self.members.values())
    def raw_file(self,fid):return self.storage[fid]['raw']
    def stored_files(self,name):return []
    def upload(self,doc):
        self.uploads+=1;fid=str(self.uploads);self.storage[fid]=dict(doc,id=fid);return fid
    def wait(self,fid,seconds):
        if self.fail_wait:raise ingestion.IngestionError('test interruption')
    def add(self,kb,fid):self.members[fid]={'id':fid,'filename':self.storage[fid]['filename']}
    def remove(self,kb,fid):self.members.pop(fid,None)


class IngestionApprovalTests(unittest.TestCase):
    setUp = ReviewTests.setUp
    action = ReviewTests.action
    def test_pending_approved_snapshot_survives_new_revision(self):
        self.action('approve')
        config={'base_url':'http://127.0.0.1:8080','collection_id':'kb','meetings_root':str(self.root)}
        state=ingestion.State(self.root/'state.json',config)
        client=FakeClient();client.fail_wait=True
        result=ingestion.sync(client,config,state,apply=True,busy=lambda _:False)
        self.assertTrue(result['errors'])
        pending=state.data['meetings'][self.folder.name]['pending']
        self.assertEqual(pending['approval_revision'],1)
        self.action('replace',content='New user-reviewed content.')
        self.action('approve',revision=2)
        client.fail_wait=False
        result=ingestion.sync(client,config,state,apply=True,busy=lambda _:False)
        self.assertFalse(result['errors'])
        self.assertEqual(state.data['meetings'][self.folder.name]['committed']['approval_revision'],1)
        result=ingestion.sync(client,config,state,apply=True,busy=lambda _:False)
        self.assertFalse(result['errors'])
        self.assertEqual(state.data['meetings'][self.folder.name]['committed']['approval_revision'],2)
        self.assertEqual(len(client.members),1)
        self.assertEqual(client.uploads,2)


if __name__=='__main__':
    unittest.main(verbosity=2)
