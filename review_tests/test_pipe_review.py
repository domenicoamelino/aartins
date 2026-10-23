"""Open WebUI command-routing tests with a simulated HTTP client."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
import test_workflow as fixture


class Response:
    status_code=200
    def __init__(self,value):self.value=value
    def json(self):return self.value
    def raise_for_status(self):pass


class Client:
    calls=[]
    def __init__(self,**kw):pass
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def get(self,url,**kw):
        self.calls.append(('get',url,kw))
        return Response({'id':'a'*32,'revision':3,'report':'# Reviewed draft','transcript':'# Transcript',
                         'changes':'-old\n+new','review_state':'draft','pending':None})
    async def post(self,url,**kw):
        self.calls.append(('post',url,kw))
        return Response({'message':'Saved','id':'a'*32,'revision':3})


class PipeReviewTests(unittest.TestCase):
    def setUp(self):
        Client.calls=[]
        path=fixture.PLATFORM/'openwebui_meeting_pipe.py'
        spec=importlib.util.spec_from_file_location('review_pipe_under_test',path)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'httpx':types.SimpleNamespace(AsyncClient=Client),
                                    'pydantic':types.SimpleNamespace(BaseModel=type('BaseModel',(),{}),Field=lambda default=None,**kw:default)}):
            spec.loader.exec_module(module)
        self.pipe=module.Pipe()
        self.pipe.valves.WORKER_API_KEY='test'
        self.pipe.valves.PUBLIC_ORIGIN='https://local.example'

    def call(self,text):
        return asyncio.run(self.pipe.pipe({'messages':[{'role':'user','content':text}]},
            __user__={'id':'alice'},__chat_id__='chat',__message_id__='message'))

    def test_commands_use_owner_authenticated_review_endpoint(self):
        jid='a'*32
        for command,action in (
            (f'approve {jid} 3','approve'),
            (f'retry {jid} 3','retry'),
            (f'feedback {jid} 3\nKeep the negation.','feedback'),
            (f'replace {jid} 3\nMy reviewed recap.','replace'),
            (f'speakers {jid} 3\nSPEAKER_00 = Domenico\nSPEAKER_01 = Jan Willem','speakers'),
            (f'correct {jid} 3 S000012\nThere is no role document.','correct'),
            (f'speaker {jid} 3 S000012 = Domenico','speaker'),
            (f'date {jid} 3 2026-10-23','metadata'),
            (f'title {jid} 3\nPlanning meeting','metadata'),
            (f'participants {jid} 3\nDomenico, Jan Willem','metadata'),
        ):
            with self.subTest(action=action):
                self.call(command)
                method,url,args=Client.calls[-1]
                self.assertEqual(method,'post')
                self.assertTrue(url.endswith('/'+jid+'/review'))
                self.assertEqual(args['json']['action'],action)
                self.assertEqual(args['json']['revision'],3)
                self.assertEqual(args['headers']['X-Owner-Id'],'alice')
        self.assertTrue(all(not url.endswith('/v1/sessions') for _,url,_ in Client.calls))

    def test_read_and_non_exact_approval(self):
        jid='a'*32
        self.assertIn('Reviewed draft',self.call('review '+jid))
        self.assertIn('Transcript',self.call('transcript '+jid))
        self.assertIn('diff',self.call('changes '+jid))
        Client.calls=[]
        text=self.call(f'approve {jid} 3 because the transcript said so')
        self.assertIn('Only',text)
        self.assertFalse(Client.calls)


if __name__=='__main__':unittest.main(verbosity=2)

