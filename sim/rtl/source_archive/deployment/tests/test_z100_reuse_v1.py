"""The extra operand stage must preserve issue counts and invalidate on cancel."""
import copy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from validate_z100_reuse_v1 import parse_sim_output


class ReuseV1Tests(unittest.TestCase):
    def test_actual_sim_has40jobs_and_all_eight_stage_cancellations(self):
        base=ROOT/'validation/board_z100/reuse_core_v1/20261021T131149Z_0374aed8'
        parsed=parse_sim_output((base/'xsim.log').read_text())
        self.assertEqual(parsed['jobs'],40)
        self.assertEqual(parsed['abort_checks_passed'],8)
        for row in parsed['metrics']:
            self.assertEqual(row['pipeline_flush'],4)
            self.assertEqual(row['start_to_result'],(row['taps']+3)//4+4)

    def test_old_latency_or_failure_marker_cannot_pass(self):
        base=ROOT/'validation/board_z100/reuse_core_v1/20261021T131149Z_0374aed8'
        text=(base/'xsim.log').read_text()
        with self.assertRaises(ValueError):parse_sim_output(text+'\nFAIL: injected cancel bug')
        with self.assertRaises(ValueError):parse_sim_output(text.replace('pipeline_flush=4','pipeline_flush=3',1))


if __name__=='__main__':unittest.main()
