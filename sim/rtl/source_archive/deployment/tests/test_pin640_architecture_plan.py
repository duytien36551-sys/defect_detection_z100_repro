"""Check finite ownership scheduling and the actual exported640 feasibility model."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from z100_pin640_architecture_plan import allocate,flowshop,fuse_silu,plan,validate_graph


class Pin640ArchitecturePlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=ROOT/'deployment/candidates/pin640/validation/20261021_verified/pin/pipeline/model'
        cls.graph=json.loads((cls.model/'graph.json').read_text(encoding='utf-8'))
        cls.report=plan(cls.graph,cls.model/'weights_float.npz')

    def test_baseline_reproduces_actual_tile_schedule(self):
        totals=self.report['baseline']['totals']
        self.assertEqual(totals['logical_macs'],4323744000)
        self.assertEqual(totals['tap_cycles_lower_bound'],93510400)
        self.assertEqual((totals['load_calls'],totals['run_calls']),(100,6583))
        self.assertEqual(totals['load_tx_bytes']+totals['run_tx_bytes'],97155520)
        self.assertEqual(totals['response_rx_bytes'],58138460)

    def test_graph_has_no_unpriced_operators(self):
        self.assertEqual(self.report['graph_nodes'],163)
        self.assertEqual(len(self.report['nonconvolution']),100)
        self.assertTrue(all(x['read_bytes']>0 and x['write_bytes']>0 for x in self.report['nonconvolution']))
        self.assertTrue(all(x['implementation'].startswith('NOT_IMPLEMENTED') for x in self.report['nonconvolution']))
        self.assertTrue(all(p['nonconv_and_arm_requant_cost']=='UNKNOWN_NOT_FREE' for p in self.report['private_hypotheses']))

    def test_bank_is_held_until_drain_and_overlap_is_not_free(self):
        jobs=[(5,3,2)]*2
        single=flowshop(jobs,1);double=flowshop(jobs,2)
        self.assertEqual(single['cycles'],20)
        self.assertEqual(double['cycles'],15)
        self.assertEqual(double['serialized_cycles'],20)
        self.assertEqual(single['sample'][1]['load'][0],10)
        self.assertEqual(double['sample'][1]['load'][0],5)
        for invalid in (0,-1):
            with self.assertRaises(ValueError):flowshop(jobs,invalid)

    def test_single_consumer_fusion_retains_integer_boundary_and_lifetimes(self):
        fused=fuse_silu(self.graph)
        self.assertEqual(len(fused['fusion_pairs']),57)
        self.assertEqual(len(fused['nodes']),106)
        self.assertEqual(sum(len(x['original_ids']) for x in fused['nodes']),163)
        original=self.report['original_memory'];memory=self.report['fused_memory']
        self.assertEqual(original['arena_bytes'],3276800)
        self.assertLess(memory['arena_bytes'],original['arena_bytes'])
        for row in memory['allocations']:
            self.assertEqual(row['offset']%64,0)
            self.assertLessEqual(row['offset']+row['bytes'],memory['arena_bytes'])
            for other in memory['allocations'][:row['node']]:
                if other['last_use']>=row['node']:
                    self.assertTrue(row['offset']>=other['offset']+other['bytes'] or
                                    other['offset']>=row['offset']+row['bytes'])

    def test_extra_consumer_prevents_fusion(self):
        graph=copy.deepcopy(self.graph)
        graph['outputs'][0]=0
        self.assertNotIn([0,1],fuse_silu(graph)['fusion_pairs'])

    def test_unknown_operator_bad_dependency_and_wrong_resolution_are_rejected(self):
        for key,value in (('op','opaque'),('inputs',[163]),('shape',[1,16,0,320])):
            graph=copy.deepcopy(self.graph);graph['nodes'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_graph(graph)
        graph=copy.deepcopy(self.graph);graph['input_shape']=[1,3,416,416]
        with self.assertRaises(ValueError):validate_graph(graph)

    def test_ruleout_is_arithmetic_and_not_a_fps_claim(self):
        self.assertGreater(self.report['arithmetic512_min_ms'],1000/30)
        self.assertAlmostEqual(self.report['private_hypotheses'][0]['ideal_compute_ms'],45.944)
        self.assertAlmostEqual(self.report['private_hypotheses'][2]['ideal_compute_ms'],22.972)
        self.assertFalse(self.report['graph_resident_hypothesis']['eligible_for30fps'])
        self.assertFalse(self.report['all_nonboard_engineering_complete'])
        self.assertFalse(self.report['physical_board_tested'])


if __name__=='__main__':unittest.main()
