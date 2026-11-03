"""Exact alias eligibility, temporal packing and retained C ABI guards."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from deployment.candidates.pin640_inplace_v1.pack_model import memory_plan_inplace

MODEL=ROOT/'deployment/candidates/pin640/validation/20261021_verified/pin/pipeline/model'
CANDIDATE=ROOT/'deployment/candidates/pin640_inplace_v1'


class Pin640InplaceTests(unittest.TestCase):
    def setUp(self):
        self.graph=json.loads((MODEL/'graph.json').read_text(encoding='utf-8'))

    def test_actual_graph_has57_safe_aliases_and512000bytes_saved(self):
        result=memory_plan_inplace(self.graph['nodes'],self.graph['outputs'],8388608)
        self.assertEqual(result['arena_bytes'],2764800)
        self.assertEqual(result['original_node_count'],163)
        self.assertEqual(len(result['fusion_pairs']),57)
        for source,silu in result['fusion_pairs']:
            self.assertEqual(result['allocations'][source]['offset'],result['allocations'][silu]['offset'])
            self.assertEqual(result['allocations'][source]['bytes'],result['allocations'][silu]['bytes'])

    def test_output_or_additional_consumer_prevents_overwrite(self):
        graph=copy.deepcopy(self.graph);graph['outputs'][0]=0
        result=memory_plan_inplace(graph['nodes'],graph['outputs'],8388608)
        self.assertNotIn([0,1],result['fusion_pairs'])
        graph=copy.deepcopy(self.graph);graph['nodes'][3]['inputs']=[0]
        result=memory_plan_inplace(graph['nodes'],graph['outputs'],8388608)
        self.assertNotIn([0,1],result['fusion_pairs'])

    def test_small_or_invalid_budget_cannot_be_treated_as_fit(self):
        result=memory_plan_inplace(self.graph['nodes'],self.graph['outputs'],1024)
        self.assertFalse(result['fits_budget'])
        for budget in (0,-1,2**32):
            with self.assertRaises(ValueError):memory_plan_inplace(self.graph['nodes'],self.graph['outputs'],budget)

    def test_baseline_sources_remain_bound(self):
        records=json.loads((CANDIDATE/'source_origin.json').read_text())['copies']
        self.assertEqual(len(records),52)
        for row in records:
            with self.subTest(path=row['source']):
                self.assertEqual(hashlib.sha256((ROOT/row['source']).read_bytes()).hexdigest(),row['sha256'])

    def test_actual_c_smoke_covers_all_backends_and_rejects_unsafe_alias(self):
        output=CANDIDATE/'validation/20261021_verified'
        result=json.loads((output/'result.json').read_text())
        self.assertEqual(result['status'],'PASS_ISOLATED_PIN640_INPLACE_INTEGER_EQUIVALENCE')
        self.assertEqual({row['backend'] for row in result['cases']},{'scalar','tile64_mock','pipeline_tile64_mock'})
        for row in result['cases']:
            self.assertEqual(row['head_values'],613200)
            self.assertEqual(row['max_error'],0)
            self.assertTrue(row['canaries_intact'])
        self.assertTrue(result['unsafe_alias_guards_passed'])
        for path,sha in result['source_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)


if __name__=='__main__':unittest.main()
