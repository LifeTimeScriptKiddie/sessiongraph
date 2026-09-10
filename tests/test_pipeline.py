import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sessiongraph.analyze import analyze, compare
from sessiongraph.cli import main
from sessiongraph.pipeline import load_pipeline


class PipelineTests(unittest.TestCase):
    def payload(self):
        return {'schema':'sessiongraph.pipeline.v1','fixture_sha256':'a'*64,'verifier_sha256':'b'*64,
                'source_sha256':'c'*64,'required_stages':['intake','resume'],
                'required_checks':{'exact-scope':'intake','saved-state':'resume'},
                'stages':[{'id':'intake','status':'completed','duration_ms':10,
                           'checks':[{'id':'exact-scope','passed':True,'evidence_sha256':'d'*64}]},
                          {'id':'resume','status':'completed','duration_ms':20,
                           'checks':[{'id':'saved-state','passed':True,'evidence_sha256':'e'*64}]}]}

    def result(self, payload):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'pipeline.json'; path.write_text(json.dumps(payload))
            return analyze(load_pipeline(path))

    def test_success_requires_completed_stages_and_all_checks(self):
        result=self.result(self.payload())
        self.assertEqual(result['metrics']['pipeline_success'],1)
        self.assertEqual(result['metrics']['pipeline_checks_passed'],2)
        self.assertEqual(result['metrics']['pipeline_duration_ms'],30)
        self.assertFalse(result['findings'])

    def test_failed_check_is_not_hidden_by_successful_process(self):
        payload=self.payload(); payload['stages'][0]['checks'][0]['passed']=False
        result=self.result(payload)
        self.assertEqual(result['metrics']['pipeline_success'],0)
        self.assertEqual(result['metrics']['pipeline_checks_failed'],1)
        self.assertTrue(result['findings'])
        self.assertIn('pipeline_contract',{item['code'] for item in result['findings']})

    def test_missing_check_cannot_shrink_denominator(self):
        payload=self.payload(); payload['stages'][0]['checks']=[]
        result=self.result(payload)
        self.assertEqual(result['metrics']['pipeline_checks_required'],2)
        self.assertEqual(result['metrics']['pipeline_checks_missing'],1)
        self.assertEqual(result['metrics']['pipeline_success'],0)

    def test_missing_stage_and_timeout_are_not_success(self):
        payload=self.payload(); payload['stages'].pop()
        self.assertEqual(self.result(payload)['metrics']['pipeline_stages_missing'],1)
        payload=self.payload(); payload['stages'][1]['status']='timeout'
        result=self.result(payload)
        self.assertEqual(result['metrics']['pipeline_timeouts'],1)
        self.assertEqual(result['metrics']['pipeline_success'],0)

    def test_comparison_keeps_contract_and_fixture_fixed(self):
        payload=self.payload(); payload['stages'][0]['checks'][0]['passed']=False
        before=self.result(payload); after=self.result(self.payload())
        result=compare(before,after)
        self.assertEqual(result['delta']['pipeline_checks_passed'],1)
        self.assertEqual(result['delta']['pipeline_success'],1)
        self.assertTrue(result['comparable'])
        for field in ['fixture_sha256','verifier_sha256']:
            changed=self.payload(); changed[field]='f'*64
            with self.assertRaises(ValueError): compare(before,self.result(changed))
        changed=self.payload(); changed['required_checks']['extra']='resume'
        with self.assertRaises(ValueError): compare(before,self.result(changed))
        other=copy.deepcopy(before);other['session']['format']='generic-jsonl'
        with self.assertRaises(ValueError): compare(before,other)

    def test_source_revision_can_change(self):
        changed=self.payload();changed['source_sha256']='f'*64
        self.assertTrue(compare(self.result(self.payload()),self.result(changed))['comparable'])

    def test_cli_refuses_incomparable_runs_without_writing_comparison(self):
        before=self.result(self.payload())
        changed=self.payload();changed['verifier_sha256']='f'*64
        after=self.result(changed)
        with TemporaryDirectory() as directory:
            root=Path(directory);left=root/'before.json';right=root/'after.json';out=root/'comparison.json'
            left.write_text(json.dumps(before));right.write_text(json.dumps(after))
            self.assertEqual(main(['compare',str(left),str(right),'--out',str(out)]),2)
            self.assertFalse(out.exists())

    def test_failed_contract_suggests_verification_not_blind_retry(self):
        payload=self.payload();payload['stages'][0]['checks']=[]
        result=self.result(payload)
        with TemporaryDirectory() as directory:
            path=Path(directory)/'analysis.json';path.write_text(json.dumps(result));out=Path(directory)/'suggest'
            self.assertEqual(main(['suggest-workflow',str(path),'--target','agentctl','--out',str(out)]),0)
            self.assertIn('pipeline_checks_required unchanged',(out/'rationale.md').read_text())
            self.assertIn('Verification contract',(out/'run.yaml').read_text())

    def test_bad_durations_verdicts_digests_and_duplicate_records_rejected(self):
        variants=[]
        for duration in [True,-1,'slow',float('nan'),float('inf'),10**400]:
            p=self.payload();p['stages'][0]['duration_ms']=duration;variants.append(p)
        for verdict in [1,'true',None]:
            p=self.payload();p['stages'][0]['checks'][0]['passed']=verdict;variants.append(p)
        p=self.payload();p['fixture_sha256']='secret';variants.append(p)
        p=self.payload();p['required_checks']={};variants.append(p)
        p=self.payload();p['stages'].append(p['stages'][0]);variants.append(p)
        p=self.payload();p['stages'][0]['checks']*=2;variants.append(p)
        p=self.payload();p['stages'][0]['checks'][0]['id']='unknown';variants.append(p)
        p=self.payload();p['stages'][0]['status']='success-ish';variants.append(p)
        p=self.payload();p['stages'][0]['status']=[];variants.append(p)
        p=self.payload();p['stages'].reverse();variants.append(p)
        p=self.payload()
        for stage in p['stages']: stage['duration_ms']=10**308
        variants.append(p)
        p=self.payload()
        for stage in p['stages']: stage['duration_ms']=10**308
        p['required_stages'].append('finish')
        p['stages'].append({'id':'finish','status':'completed','duration_ms':1.0,'checks':[]})
        variants.append(p)
        for payload in variants:
            with self.subTest(payload=payload),self.assertRaises(ValueError): self.result(payload)

    def test_private_payload_fields_and_names_are_not_exported(self):
        payload=self.payload();payload['secret']='PRIVATE_CONTENT'
        payload['required_stages'][0]='PRIVATE_STAGE'
        payload['required_checks']['exact-scope']='PRIVATE_STAGE'
        payload['stages'][0]['id']='PRIVATE_STAGE'
        payload['stages'][0]['stdout']='PRIVATE_CONTENT'
        with TemporaryDirectory() as directory:
            path=Path(directory)/'pipeline.json';path.write_text(json.dumps(payload));out=Path(directory)/'out'
            self.assertEqual(main(['analyze-pipeline',str(path),'--out',str(out)]),0)
            for artifact in out.iterdir():
                self.assertNotIn('PRIVATE_',artifact.read_text())
                self.assertNotIn(str(path),artifact.read_text())
            self.assertIn('Reported verification', (out/'report.md').read_text())


if __name__=='__main__': unittest.main()
