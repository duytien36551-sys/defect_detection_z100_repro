"""Address/port contract tests for the PIN640 32x4x8 window candidate."""

import json
import os
from pathlib import Path
import unittest

from tools import z100_pin640_window_banks as windows


REPO_ROOT = Path(__file__).resolve().parents[2]


def make_layer(cin, cout, hin, win, kernel, stride, padding):
    hout = (hin + 2 * padding - kernel) // stride + 1
    wout = (win + 2 * padding - kernel) // stride + 1
    taps = cin * kernel * kernel
    groups = windows.ceil_div(cout, 32)
    return {
        "input_channels": cin,
        "output_channels": cout,
        "input_height": hin,
        "input_width": win,
        "output_height": hout,
        "output_width": wout,
        "kernel": kernel,
        "stride": stride,
        "padding": padding,
        "tap_count": taps,
        "output_channel_groups": groups,
    }


class Pin640WindowBankTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = windows.load_project(REPO_ROOT)

    def test_verified_graph_and_memory_plan_bind_all_63_convolutions(self):
        layers = self.project["layers"]
        self.assertEqual(len(layers), 63)
        self.assertEqual(len({row["node_id"] for row in layers}), 63)
        self.assertEqual(sum(row["row_aware_issue_count"] for row in layers), 4_753_600)
        self.assertEqual(sum(row["old_flatten_issue_count"] for row in layers), 4_594_400)
        self.assertEqual(
            sum(row["row_aware_issue_count"] - row["old_flatten_issue_count"]
                for row in layers),
            159_200,
        )
        self.assertEqual(self.project["validation_result"]["checkpoint_role"],
                         "initial_interface_fixture_not_final")

    def test_hand_computed_k1_stride1_site_tail_and_tap_tail_are_independent(self):
        layer = make_layer(cin=1, cout=1, hin=1, win=3,
                           kernel=1, stride=1, padding=0)
        slots = list(windows.iter_issue_slots(layer, 0, 0, 0, 0))
        self.assertEqual(len(slots), 8 * 4)
        self.assertEqual(sum(slot["valid"] for slot in slots), 3)
        self.assertEqual(sum(slot["site_tail"] for slot in slots), 5 * 4)
        self.assertEqual(sum(slot["tap_tail"] for slot in slots), 8 * 3)
        self.assertEqual(sum(slot["padding"] for slot in slots), 0)
        self.assertTrue(slots[0]["valid"])
        self.assertEqual(slots[0]["scalar_nchw_byte_index"], 0)
        self.assertTrue(slots[1]["tap_tail"])
        self.assertTrue(slots[12]["site_tail"])
        self.assertTrue(slots[13]["site_tail"] and slots[13]["tap_tail"])

    def test_hand_computed_k3_stride1_padding_and_nchw_tap_order(self):
        layer = make_layer(cin=1, cout=8, hin=3, win=4,
                           kernel=3, stride=1, padding=1)
        first_tap_issue = list(windows.iter_issue_slots(layer, 0, 0, 0, 0))
        # NCHW flattening means tap 0=(ic0,ky0,kx0), tap 3=(ic0,ky1,kx0).
        self.assertTrue(first_tap_issue[0]["padding"])
        site1_tap3 = first_tap_issue[4 + 3]
        self.assertTrue(site1_tap3["valid"])
        self.assertEqual((site1_tap3["input_channel"], site1_tap3["kernel_y"],
                          site1_tap3["kernel_x"], site1_tap3["input_y"],
                          site1_tap3["input_x"],
                          site1_tap3["scalar_nchw_byte_index"]),
                         (0, 1, 0, 0, 0, 0))
        second_tap_issue = list(windows.iter_issue_slots(layer, 0, 0, 0, 4))
        # tap 5=(0,1,2), for output x=3, reaches x=4 and is right padding.
        site3_tap5 = second_tap_issue[3 * 4 + 1]
        self.assertTrue(site3_tap5["padding"])
        self.assertEqual((site3_tap5["kernel_y"], site3_tap5["kernel_x"],
                          site3_tap5["input_x"]), (1, 2, 4))

    def test_hand_computed_k3_stride2_padding_horizontal_tail_and_mapping(self):
        layer = make_layer(cin=1, cout=33, hin=5, win=5,
                           kernel=3, stride=2, padding=1)
        # Last output row and final valid output site stay within this row tile.
        slots = list(windows.iter_issue_slots(layer, 0, 2, 0, 4))
        site2_tap4 = slots[2 * 4 + 0]
        self.assertTrue(site2_tap4["valid"])
        self.assertEqual((site2_tap4["input_y"], site2_tap4["input_x"],
                          site2_tap4["scalar_nchw_byte_index"],
                          site2_tap4["bank"], site2_tap4["word_address"],
                          site2_tap4["generation_input_y"], site2_tap4["byte_lane"]),
                         (4, 4, 24, 1, 1, 4, 0))
        self.assertEqual(sum(slot["site_tail"] for slot in slots), 5 * 4)
        last_tap_issue = list(windows.iter_issue_slots(layer, 0, 2, 0, 8))
        self.assertTrue(last_tap_issue[2 * 4]["padding"])
        self.assertTrue(last_tap_issue[2 * 4 + 1]["tap_tail"])

    def test_broadcast_dedup_and_three_word_two_port_conflict(self):
        requests = [
            {"valid": True, "bank": 2, "word_address": 10, "generation_input_y": 7},
            {"valid": True, "bank": 2, "word_address": 10, "generation_input_y": 7},
            {"valid": True, "bank": 2, "word_address": 11, "generation_input_y": 7},
            {"valid": True, "bank": 2, "word_address": 12, "generation_input_y": 7},
        ]
        unique = windows.dedupe_issue_requests(requests)
        self.assertEqual(len(unique), 3)
        service = windows.port_service_cycles(requests)
        self.assertEqual(service["bank_unique_words"][2], 3)
        self.assertEqual(service["serialized_read_service_cycles"], 2)
        self.assertEqual(service["port_stall_cycles"], 1)

    def test_ring_generation_alias_is_rejected_not_broadcast_or_free_port(self):
        requests = [
            {"valid": True, "bank": 9, "word_address": 17, "generation_input_y": 2},
            {"valid": True, "bank": 9, "word_address": 17, "generation_input_y": 5},
        ]
        with self.assertRaisesRegex(ValueError, "ring-generation alias"):
            windows.dedupe_issue_requests(requests)

    def test_full_run_report_proves_all_valid_slots_were_scalar_checked(self):
        report_path = os.environ.get("Z100_WINDOW_BANKS_REPORT")
        if not report_path:
            self.skipTest("set Z100_WINDOW_BANKS_REPORT to the fresh exhaustive result.json")
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        expected_ids = [row["node_id"] for row in self.project["layers"]]
        windows.validate_completed_report(report, expected_ids)
        self.assertEqual(report["totals"]["issues"], 4_753_600)
        self.assertEqual(report["totals"]["scalar_address_checks"],
                         report["totals"]["valid_byte_requests"])


if __name__ == "__main__":
    unittest.main()
