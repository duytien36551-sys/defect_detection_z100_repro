import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import validate_z100_reuse_bridge as bridge


class BridgeValidationTests(unittest.TestCase):
    def test_actual_bridge_trace_has_stall_cancel_reset_and_error_coverage(self):
        path=ROOT/'validation/board_z100/reuse_core_v1/20261021T133134Z_4cce0508/xsim.log'
        result=bridge.parse_result(path.read_text())
        self.assertEqual(result,dict(commands=159,results=20,cancels=6,errors=2,resets=1))

    def test_failure_or_missing_activity_cannot_pass(self):
        line='BRIDGE_PASS commands=159 results=20 cancels=6 errors=2 resets=1'
        for text in (line+'\nFatal: stale result',line.replace('resets=1','resets=0'),
                     line.replace('errors=2','errors=0'),line+'\n'+line):
            with self.subTest(text=text),self.assertRaises(ValueError):bridge.parse_result(text)


if __name__=='__main__':unittest.main()
