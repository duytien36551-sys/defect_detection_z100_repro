import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import z100_requant_context_map as mapping

MINIMUM = -(1 << 31)
MAXIMUM = (1 << 31) - 1
SENTINEL = 1 << 31


class RequantContextMapTests(unittest.TestCase):
    def test_all_255_sorted_indices_biject_onto_expected_stage_nodes(self):
        proof = mapping.verify_complete_mapping()
        self.assertEqual(proof["stage_nodes"], [1, 2, 4, 8, 16, 32, 64, 128])
        self.assertEqual(mapping.index_to_stage_node(254), (7, 127))
        self.assertEqual(mapping.stage_node_to_index(7, 127), 254)

    def test_context_addresses_do_not_alias_between_contexts_or_stages(self):
        addresses = {
            (context, stage, node): mapping.physical_address(context, stage, node)
            for context in range(8)
            for stage in range(8)
            for node in range(1 << stage)
        }
        for context in range(8):
            for stage in range(8):
                values = [addresses[context, stage, node] for node in range(1 << stage)]
                self.assertEqual(values, list(range(context << stage, (context + 1) << stage)))

    def test_tree_search_handles_minimum_duplicates_and_never_crosses_sentinel(self):
        cases = [
            [MINIMUM] * 254 + [SENTINEL],
            [SENTINEL] * 255,
            [MINIMUM] * 5 + [-1] * 5 + [0] * 5 + [MAXIMUM] * 5 + [SENTINEL] * 235,
        ]
        probes = (MINIMUM, MINIMUM + 1, -1, 0, 1, MAXIMUM - 1, MAXIMUM)
        for tree in cases:
            banks = mapping.banked_table(tree)
            for raw in probes:
                expected = sum(key <= raw for key in tree[:254])
                rank = mapping.search_banked_rank(banks, raw)
                self.assertEqual(rank, expected)
                self.assertLessEqual(rank, 254)

    def test_rejects_unreachable_index_invalid_context_and_missing_sentinel(self):
        with self.assertRaisesRegex(ValueError, "0..254"):
            mapping.index_to_stage_node(255)
        with self.assertRaisesRegex(ValueError, "0..7"):
            mapping.physical_address(8, 0, 0)
        with self.assertRaisesRegex(ValueError, "key index 254"):
            mapping.banked_table([0] * 255)


if __name__ == "__main__":
    unittest.main()
