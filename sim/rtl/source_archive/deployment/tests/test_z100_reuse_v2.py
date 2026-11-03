import hashlib
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from validate_z100_reuse_v1 import parse_sim_output


class ReuseV2Tests(unittest.TestCase):
    def test_free_running_data_preserves_numerics_latency_and_all_reset_cancel_stages(self):
        launch=ROOT/'validation/board_z100/reuse_core_v2/20261021T134503Z_259864d1/launch.json'
        identities=json.loads(launch.read_text())['source_sha256']
        for relative,digest in identities.items():
            self.assertEqual(hashlib.sha256((ROOT/relative).read_bytes()).hexdigest(),digest)
        summary=parse_sim_output((launch.parent/'xsim.log').read_text())
        self.assertEqual(summary['jobs'],40)
        self.assertEqual(summary['abort_checks_passed'],8)
        self.assertTrue(all(row['pipeline_flush']==4 for row in summary['metrics']))


if __name__=='__main__':unittest.main()
