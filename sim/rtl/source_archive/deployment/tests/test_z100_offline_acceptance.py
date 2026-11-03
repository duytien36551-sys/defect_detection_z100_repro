"""Exercise fail-closed orchestration and evidence-corruption boundaries."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('suite',ROOT/'tools/accept_z100_offline.py')
suite=importlib.util.module_from_spec(spec);spec.loader.exec_module(suite)


class OfflineAcceptanceTests(unittest.TestCase):
    def test_missing_and_changed_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'deployment/build') as folder:
            p=Path(folder)/'input';p.write_text('original');expected=suite.sha(p)
            suite.verify_file(p,expected);p.write_text('changed')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):suite.verify_file(p,expected)
            p.unlink()
            with self.assertRaisesRegex(ValueError,'missing file'):suite.verify_file(p,expected)

    def test_stop_before_next_case(self):
        visits=[]
        def run(case):
            visits.append(case)
            if case=='bad':raise ValueError('failed tool')
            return case
        with self.assertRaises(ValueError):suite.execute_steps(['ok','bad','must_not_run'],run)
        self.assertEqual(visits,['ok','bad'])

    def test_multiline_runner_json(self):
        summary=dict(status='PASS',report='fresh/result.json',variants=[dict(enabled=0)])
        self.assertEqual(suite.runner_summary('prior output\n'+json.dumps(summary,indent=2)+'\n'),summary)
        with self.assertRaises(ValueError):suite.runner_summary(json.dumps(summary)+'\nFAIL late failure\n')

    def test_duplicate_or_missing_manifest_case(self):
        manifest=suite.read(suite.MANIFEST)
        missing=copy.deepcopy(manifest);missing['cases'].pop()
        with self.assertRaisesRegex(ValueError,'case manifest'):suite.preflight(missing)
        duplicate=copy.deepcopy(manifest);duplicate['cases'][1]=duplicate['cases'][0]
        with self.assertRaisesRegex(ValueError,'case manifest'):suite.preflight(duplicate)

    def test_negative_case_identity(self):
        manifest=suite.read(suite.MANIFEST);manifest['cases'][0]['expected_negative']=True
        with self.assertRaisesRegex(ValueError,'negatives changed'):suite.preflight(manifest)

    def test_collision_is_rejected_by_real_parser(self):
        helper=suite.load_helpers()['core']
        path=next(x for x in suite.read(suite.MANIFEST)['cases'] if x['id']=='core_wrap')['result']
        report=suite.read(ROOT/path);text=Path(report['commands'][-1]['log']).read_text()
        helper.parse_observers(text,'wrap')
        with self.assertRaises(AssertionError):helper.parse_observers(text.replace('collisions=0','collisions=1',1),'wrap')

    def test_negative_case_cannot_reuse(self):
        helpers=suite.load_helpers();manifest=suite.read(suite.MANIFEST)
        case=next(x for x in manifest['cases'] if x['id']=='fault_permanent_read')
        report=suite.read(ROOT/case['result'])
        # Supply a valid log/hash with an extra reload claim. Raw semantic check
        # must still reject it even though the new log's own hash is consistent.
        with tempfile.TemporaryDirectory(dir=ROOT/'deployment/build') as folder:
            folder=Path(folder);log=folder/'xsim.log'
            log.write_text(Path(report['commands'][-1]['log']).read_text()+'\nCOVERAGE reload=PROBE_LOAD_RUN\n')
            report['commands'][-1]['log']=str(log);report['commands'][-1]['log_sha256']=suite.sha(log)
            path=folder/'result.json';path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'negative-case reuse'):suite.check_case(case,path,helpers)


if __name__=='__main__':unittest.main()
