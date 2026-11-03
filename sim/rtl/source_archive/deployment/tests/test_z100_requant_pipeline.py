import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import z100_requant_thresholds as rq
import validate_z100_requant_pipeline as pipeline


class RequantPipelineHostTests(unittest.TestCase):
    def test_appends_one_never_crossed_sentinel_and_keeps_duplicates(self):
        original = [rq.MINIMUM] * 4 + [-1] * 3 + [0] * 2 + [rq.SENTINEL] * 245
        tree = pipeline.append_sentinel(original)
        self.assertEqual(len(tree), 255)
        self.assertEqual(tree[-2:], (rq.SENTINEL, rq.SENTINEL))
        self.assertEqual(pipeline.tree_search_upper_bound(tree, rq.MINIMUM), 4 - 127)
        self.assertEqual(pipeline.tree_search_upper_bound(tree, -1), 7 - 127)
        self.assertEqual(pipeline.tree_search_upper_bound(tree, 0), 9 - 127)
        self.assertEqual(pipeline.tree_search_upper_bound(tree, pipeline.MAX_I32), 9 - 127)

    def test_all_minimum_and_all_sentinel_tables_cover_extreme_outputs(self):
        all_minimum = pipeline.append_sentinel([rq.MINIMUM] * 254)
        all_sentinel = pipeline.append_sentinel([rq.SENTINEL] * 254)
        for raw in (rq.MINIMUM, -1, 0, pipeline.MAX_I32):
            self.assertEqual(pipeline.tree_search_upper_bound(all_minimum, raw), 127)
            self.assertEqual(pipeline.tree_search_upper_bound(all_sentinel, raw), -127)

    def test_threshold_neighbors_match_direct_upper_bound_and_existing_oracle(self):
        for multiplier in (0.5, 1.0, 2.0, math.nextafter(0.5, 1.0), 2.0 ** -40):
            original = tuple(rq.thresholds(multiplier))
            tree = pipeline.append_sentinel(original)
            for key in original:
                for raw in (key - 1, key, key + 1):
                    if rq.MINIMUM <= raw <= pipeline.MAX_I32:
                        self.assertEqual(pipeline.direct_upper_bound(original, raw),
                                         pipeline.tree_search_upper_bound(tree, raw))
                        self.assertEqual(pipeline.tree_search_upper_bound(tree, raw), rq.oracle(raw, multiplier))

    def test_rejects_nonmonotone_out_of_range_and_wrong_sized_tables(self):
        with self.assertRaisesRegex(ValueError, "nondecreasing"):
            pipeline.append_sentinel([0, -1] + [0] * 252)
        with self.assertRaisesRegex(ValueError, "range"):
            pipeline.append_sentinel([rq.SENTINEL + 1] * 254)
        with self.assertRaisesRegex(ValueError, "254"):
            pipeline.append_sentinel([0] * 253)
        with self.assertRaisesRegex(ValueError, "signed INT32"):
            pipeline.direct_upper_bound([0] * 254, pipeline.MAX_I32 + 1)

    def test_tree_search_rejects_missing_or_misplaced_sentinel(self):
        with self.assertRaisesRegex(ValueError, "255 keys"):
            pipeline.tree_search_upper_bound((0,) * 254, 0)
        with self.assertRaisesRegex(ValueError, "255 keys"):
            pipeline.tree_search_upper_bound(tuple([0] * 255), 0)


if __name__ == "__main__":
    unittest.main()
