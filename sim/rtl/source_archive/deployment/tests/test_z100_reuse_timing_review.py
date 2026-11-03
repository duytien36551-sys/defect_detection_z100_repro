import copy
import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import review_z100_reuse_timing as review


class TimingReviewTests(unittest.TestCase):
    def setUp(self):
        self.evidence=ROOT/'validation/board_z100/reuse_sync_fixture/20261021T130404Z_2da5e005'
        self.summary=review.parse_summary((self.evidence/'timing_routed.rpt').read_text())

    def test_actual_summary_includes_pulse_and_endpoint_counts(self):
        self.assertTrue(review.timing_pass(self.summary))
        self.assertEqual(self.summary['wpws_ns'],4.6)
        self.assertEqual(self.summary['setup_endpoints'],58986)

    def test_positive_setup_does_not_hide_pulse_hold_or_zero_activity(self):
        for key,value in [('whs_ns',-.001),('wpws_ns',-.001),('pulse_failing',1),
                          ('setup_failing',1),('setup_endpoints',0),('hold_endpoints',0)]:
            with self.subTest(key=key):
                modified=copy.deepcopy(self.summary);modified[key]=value
                self.assertFalse(review.timing_pass(modified))

    def test_open_fixture_drc_is_explicit_and_new_findings_reject(self):
        text=(self.evidence/'drc_routed.rpt').read_text()
        self.assertEqual(set(review.parse_drc(text)),set(review.OOC_RULES))
        with self.assertRaisesRegex(ValueError,'Unexpected DRC'):
            review.parse_drc(text.replace('RTSTAT-10','LUTAR-1'))
        with self.assertRaisesRegex(ValueError,'Unexpected DRC'):
            review.parse_drc(text.replace('| RTSTAT-10 | Warning','| RTSTAT-10 | Error'))

    def test_independent_review_preserves_original_parser_failure(self):
        result=review.review(self.evidence)
        self.assertEqual(result['status'],'PASS_ISOLATED_SYNC_TIMING_DRC_OPEN')
        self.assertEqual(result['original_status'],'EVIDENCE_PARSE_FAILED')
        self.assertFalse(result['bitstream_eligible'])


if __name__=='__main__':unittest.main()
