import math
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import z100_requant_thresholds as rq


class RequantThresholdTests(unittest.TestCase):
    def test_ties_even_and_signed_saturation_match_full_small_domain(self):
        for multiplier in (.5,1.0,2.0,math.nextafter(.5,1.0),math.nextafter(.5,0.0)):
            table=rq.thresholds(multiplier)
            for raw in range(-600,601):
                self.assertEqual(rq.evaluate(raw,table),max(-127,min(127,round(raw*multiplier))))

    def test_unreachable_transitions_use_signed33_sentinels(self):
        table=rq.thresholds(2.0**-60)
        self.assertEqual(set(table),{rq.MINIMUM,rq.SENTINEL})
        for raw in (rq.MINIMUM,-1,0,1,rq.SENTINEL-1):self.assertEqual(rq.evaluate(raw,table),0)

    def test_invalid_multiplier_and_out_of_domain_raw_are_rejected(self):
        for multiplier in (0,-1,float('inf'),float('nan'),sys.float_info.max):
            with self.subTest(multiplier=multiplier),self.assertRaises(ValueError):rq.thresholds(multiplier)
        table=rq.thresholds(.5)
        for raw in (rq.MINIMUM-1,rq.SENTINEL,.5):
            with self.assertRaises(ValueError):rq.evaluate(raw,table)

    def test_all_actual_fixture_convolutions_use_packaged_binary64_values(self):
        rows=rq.package_multipliers(ROOT/'deployment/candidates/pin640/validation/20261021_verified/pin/pipeline/package')
        self.assertEqual(len({r['node'] for r in rows}),63)
        self.assertTrue(all(math.isfinite(r['multiplier']) and r['multiplier']>0 for r in rows))


if __name__=='__main__':unittest.main()
