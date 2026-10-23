import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import meeting_report as r

class QualityTests(unittest.TestCase):
    def test_passages_preserve_citations_and_full_text(self):
        segments = [{'id': f'S{i:06d}', 'start': float(i), 'end': float(i+1),
                     'text': 'A substantive phrase about the project. ' * 3} for i in range(1, 195)]
        chunks = r.coherent_chunks(segments, 8000)
        rebuilt = {seg['id']: '' for seg in segments}
        for chunk in chunks:
            self.assertLessEqual(len(r.wire(r.request_data(chunk)[0]).encode()), 8000)
            for unit in chunk:
                rebuilt[unit['id']] += unit['text']
        self.assertEqual(rebuilt, {seg['id']: seg['text'] for seg in segments})

    def test_narrative_uses_source_year_not_generated_finding(self):
        row = {1: {'kind': 'topic', 'sources': ['I lived there until 27.'], 'speaker_context': []}}
        for text in ('Lived there until 2027.', 'Lived there until age 27.', 'Lived there until the year 27.'):
            with self.assertRaises(r.ReportError):
                r.check_narrative({'paragraphs': [{'section':'discussion','text':text,'facts':[1]}]}, {1}, row)
        r.check_narrative({'paragraphs':[{'section':'discussion','text':'The date needs clarification.','facts':[1]}]}, {1}, row)

    def test_acknowledgment_is_not_a_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            sources={'S000001': {'id':'S000001','text':'yes please do so'}}
            items=[{'id':'S000001','text':'yes please do so'}]
            raw={'facts':[{'kind':'confirmed','topic':'Agreement','text':'They agreed to take action.',
                          'evidence':[1], 'owner':None,'deadline':None,'interpretation':None}]}
            args=types.SimpleNamespace(language='English',context=16384,output_tokens=2048,token_safety=384,max_validation_failures=6)
            client=types.SimpleNamespace(cache={},archive=Path(temp),validation_failures=0,generate=lambda *a,**kw: raw)
            with patch.object(r,'verify_claim',return_value=True):
                self.assertEqual(r.extract(client,items,sources,args), [])
            self.assertIn('acknowledgment_without_specific_decision',(Path(temp)/'omitted_claims.json').read_text())

    def test_writer_verifies_quotes_and_combines_exact_duplicate_text(self):
        def fact(sid):
            return {'kind':'topic','topic':'Work','text':'Responsibilities are unclear.',
                    'evidence':[{'id':sid,'quote':'Roles are not defined.'}],
                    'owner':None,'deadline':None,'interpretation':None}
        with tempfile.TemporaryDirectory() as temp:
            args=types.SimpleNamespace(language='English',context=16384,output_tokens=2048,token_safety=384,resume=None)
            calls=[]
            def verify(client, text, evidence):
                calls.append(evidence)
                return True
            client=types.SimpleNamespace(archive=Path(temp),generate=lambda *a,**kw: {'paragraphs':[{'section':'discussion','text':'Responsibilities are unclear.','facts':[1]}]})
            with patch.object(r,'verify_claim',side_effect=verify):
                paragraphs, rows=r.write_narrative(client,[fact('S000001'),fact('S000002')],args)
            self.assertEqual(len(paragraphs),1)
            self.assertEqual(calls[0][0]['source_quotes'],['Roles are not defined.'])

    def test_partial_narrative_keeps_valid_sibling(self):
        fact={'kind':'topic','topic':'Background','text':'Software engineering background.',
              'evidence':[{'id':'S000001','quote':'I originally come from software engineering.'}],
              'owner':None,'deadline':None,'interpretation':None}
        raw={'paragraphs':[
            {'section':'discussion','text':'Lived there until age 27.','facts':[1]},
            {'section':'discussion','text':'The speaker has a software engineering background.','facts':[1]}]}
        with tempfile.TemporaryDirectory() as temp:
            args=types.SimpleNamespace(language='English',context=16384,output_tokens=2048,token_safety=384,resume=None)
            client=types.SimpleNamespace(archive=Path(temp),generate=lambda *a,**kw: raw)
            with patch.object(r,'verify_claim',return_value=True):
                result, _=r.write_narrative(client,[fact],args)
            self.assertEqual(len(result),1)
            self.assertIn('software engineering',result[0]['text'])
            self.assertIn('ambiguous number',(Path(temp)/'omitted_claims.json').read_text())

    def test_extraction_rejects_age_from_ambiguous_number(self):
        source={'S000001': {'text':'I lived there until 27.'}}
        fact={'kind':'topic','topic':'Background','text':'Lived there until age 27.',
              'evidence':[{'id':'S000001','quote':'I lived there until 27.'}],
              'owner':None,'deadline':None,'interpretation':None}
        with self.assertRaises(r.ReportError):
            r.validate({'facts':[fact]},source,{'S000001':['I lived there until 27.']})

    def test_preference_and_purpose_need_explicit_source_support(self):
        self.assertEqual(r.claim_guard('Speaker prefers unclear roles.', 'Roles are not clearly defined.'), 'preference_not_explicit_in_source')
        self.assertEqual(r.claim_guard('Relocated to pursue PhD work.', 'I was doing a PhD there then moved to the Netherlands.'), 'causal_or_purpose_link_not_explicit_in_source')
        self.assertIsNone(r.claim_guard('I prefer clear roles.', 'I prefer clear roles.'))

    def test_past_relocation_is_background_not_an_action(self):
        fact={'kind':'action','text':'Relocated to the Netherlands in 2017.',
              'evidence':[{'quote':'I moved to the Netherlands in 2017.'}]}
        self.assertEqual(r.fact_category(fact),'topic')
        self.assertTrue(r.personal_background(fact['text']))
        self.assertEqual(r.fact_category({'kind':'action','text':'Send the report.',
                         'evidence':[{'quote':'I will send the report tomorrow.'}]}),'action')

    def test_biography_cannot_join_different_speakers(self):
        catalog={1:{'kind':'topic','sources':['Born in Eindhoven.'], 'speaker_context':[{'speaker':'SPEAKER_00'}]},
                 2:{'kind':'topic','sources':['Moved to the Netherlands.'], 'speaker_context':[{'speaker':'SPEAKER_01'}]}}
        with self.assertRaises(r.ReportError):
            r.check_narrative({'paragraphs':[{'section':'discussion','text':'The speaker was born in Eindhoven and moved to the Netherlands.','facts':[1,2]}]}, {1,2}, catalog)

    def test_bad_sentence_does_not_discard_valid_sentence(self):
        fact={'kind':'topic','topic':'Work','text':'Roles are unclear.',
              'evidence':[{'id':'S000001','quote':'Roles are not clearly defined.'}],
              'owner':None,'deadline':None,'interpretation':None}
        raw={'paragraphs':[{'section':'discussion','text':'Roles are unclear. The speaker prefers unclear roles.','facts':[1]}]}
        with tempfile.TemporaryDirectory() as temp:
            args=types.SimpleNamespace(language='English',context=16384,output_tokens=2048,token_safety=384,resume=None)
            client=types.SimpleNamespace(archive=Path(temp),generate=lambda *a,**kw: raw)
            with patch.object(r,'verify_claim',return_value=True):
                result, _=r.write_narrative(client,[fact],args)
            self.assertEqual(result[0]['text'],'Roles are unclear.')

    def test_background_is_not_sent_to_narrative_synthesis(self):
        def fact(text, quote):
            return {'kind':'topic','topic':'Work','text':text,'evidence':[{'id':'S000001','quote':quote}],
                    'owner':None,'deadline':None,'interpretation':None}
        calls=[]
        with tempfile.TemporaryDirectory() as temp:
            args=types.SimpleNamespace(language='English',context=16384,output_tokens=2048,token_safety=384,resume=None)
            def generate(*a,**kw):
                calls.extend(kw['request_meta']['items'])
                return {'paragraphs':[{'section':'discussion','text':'Roles are unclear.','facts':[2]}]}
            client=types.SimpleNamespace(archive=Path(temp),generate=generate)
            with patch.object(r,'verify_claim',return_value=True):
                result, rows=r.write_narrative(client,[fact('Born in Eindhoven.','I was born in Eindhoven.'),fact('Roles are unclear.','Roles are not clear.')],args)
            self.assertEqual([row['ref'] for row in calls],[2])
            self.assertEqual(len(rows),2)

if __name__ == '__main__':
    unittest.main()
