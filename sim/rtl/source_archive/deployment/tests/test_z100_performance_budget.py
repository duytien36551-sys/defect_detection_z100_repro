"""Hand-calculated tail, tap-padding and spatial-split accounting cases."""
import importlib.util
import io
from pathlib import Path
import struct
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('budget',ROOT/'tools/budget_z100_tile64.py')
budget=importlib.util.module_from_spec(spec);spec.loader.exec_module(budget)


class BudgetTests(unittest.TestCase):
    def test_tail_matches_eligible_cache_fixture_dimensions(self):
        x=budget.layer_budget(1,65,1,80,64,64,262140)
        self.assertEqual(x['logical_macs'],5200)
        self.assertEqual(x['tap_cycles_lower_bound'],160)
        self.assertEqual(x['load_calls'],2);self.assertEqual(x['run_calls'],4)
        self.assertEqual(x['load_tx_bytes'],640);self.assertEqual(x['run_tx_bytes'],640)
        self.assertEqual(x['response_rx_bytes'],20920)
        self.assertEqual(x['cache_ideal_packed_input_bytes'],320)

    def test_full_lane_tiles_and_spatial_tail(self):
        x=budget.layer_budget(4,128,1,65,64,64,262140)
        self.assertEqual(x['logical_macs'],33280)
        self.assertEqual(x['tap_cycles_lower_bound'],520)
        self.assertEqual(x['run_calls'],4)
        self.assertEqual(x['load_tx_bytes'],1024)
        self.assertEqual(x['response_rx_bytes'],33400)

    def test_dma_limit_splits_spatial_chunk(self):
        x=budget.layer_budget(3,3,1,10,64,64,16)
        self.assertEqual(x['taps'],3);self.assertEqual(x['padded_taps'],4)
        self.assertEqual(x['spatial_chunk'],4);self.assertEqual(x['run_calls'],3)
        self.assertEqual(x['tap_cycles_lower_bound'],30)
        self.assertEqual(x['run_tx_bytes'],40)

    def test_npy_header_without_loading_weight_array(self):
        header=b"{'descr': '<f4', 'fortran_order': False, 'shape': (65, 3, 3, 3), }\n"
        stream=io.BytesIO(b'\x93NUMPY\x01\x00'+struct.pack('<H',len(header))+header)
        self.assertEqual(budget.npy_shape(stream),(65,3,3,3))
        with self.assertRaises(ValueError):budget.npy_shape(io.BytesIO(b'invalid'))


if __name__=='__main__':unittest.main()
