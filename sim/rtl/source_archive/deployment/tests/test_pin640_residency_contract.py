"""Evidence-bound checks for PIN640 residency and requant feasibility bounds."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from z100_pin640_residency_contract import (  # noqa: E402
    build_contract,
    lane_grouping,
    required_ports_for_issue,
    threshold_geometry,
)


class Pin640ResidencyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = build_contract()

    def test_all_graph_nodes_and_operator_work_are_accounted(self):
        graph = self.contract["graph"]
        self.assertEqual(graph["nodes"], 163)
        self.assertTrue(graph["every_original_node_accounted"])
        self.assertEqual(graph["operator_counts"], {
            "conv": 63, "silu": 57, "slice": 16, "add": 6,
            "concat": 16, "maxpool": 3, "upsample": 2,
        })
        self.assertEqual(len(graph["node_accounting"]), 163)
        self.assertEqual(graph["conv_raw_output_values_per_frame"], 14_501_200)
        self.assertEqual(graph["all_node_write_bytes_per_frame_from_planner"], 40_420_000)

    def test_exact_threshold_capacity_and_device_gate(self):
        section = self.contract["requant_threshold_tables"]
        geometry = section["geometry"]
        self.assertEqual(geometry["raw_bits_tightly_packed"], 46_226_730)
        self.assertEqual(geometry["raw_bytes_tightly_packed"], 5_778_342)
        self.assertEqual(geometry["bytes_if_each_channel_byte_aligned"], 5_779_720)
        self.assertEqual(geometry["compact_five_byte_container_bytes"], 7_004_050)
        self.assertEqual(geometry["serialized_int64_bytes"], 11_206_480)
        self.assertEqual(section["device_capacity"]["bram36_tiles"], 755)
        self.assertEqual(section["flat_single_read_port_ram18_block_lower_bound_at_33x512"], 2_736)
        self.assertEqual(section["flat_single_read_port_ram18_blocks_at_256_slot_stride"], 2_758)
        self.assertEqual(section["per_channel_bank_ramb18_estimate_from_ooc_table"], 5_515)
        self.assertTrue(section["threshold_alone_exceeds_full_device_raw_capacity"])
        self.assertTrue(section["flat_single_read_port_ram18_blocks_exceed_device"])
        self.assertEqual(section["serial_single_table_configuration_cycles_for_all_channel_tables"], 1_406_325)
        self.assertIn("cfg_begin then 254 accepted threshold writes", section["serial_configuration_scope"])

    def test_search_depth_and_cycle_bounds_do_not_treat_max_as_minimum(self):
        candidates = self.contract["throughput_candidates"]
        arithmetic = candidates["conv_timing_reference_bounds"]
        self.assertEqual(arithmetic["512mac_200mhz_arithmetic_ms_not_measured"], 42.2240625)
        self.assertEqual(arithmetic["generic_1024mac_200mhz_logical_arithmetic_ms_not_measured"], 21.11203125)
        self.assertEqual(arithmetic["generic_1024mac_logical_macs"], 4_323_744_000)
        self.assertEqual(arithmetic["plan_private_32x4x8_grouped_issue_ms_not_measured"], 22.971999999999998)
        self.assertIn("not a generic", arithmetic["plan_private_issue_definition"])
        self.assertFalse(arithmetic["implemented"])
        self.assertFalse(arithmetic["includes_requant_or_nonconv_or_io"])
        serial = candidates["serial_measured_rtl"]
        self.assertEqual(serial["cycles_per_value_min_max"], [14, 16])
        self.assertEqual(serial["cycles_per_frame_min_max"], [203_016_800, 232_019_200])
        self.assertEqual(serial["ms_per_frame_at_assumed_200mhz_min_max"], [1_015.084, 1_160.096])
        self.assertIn("UNKNOWN", serial["full_channel_table_residency_or_reload"])

        vector = candidates["32_independent_serial_searchers_by_channel_tile"]
        self.assertEqual(vector["vector_tasks_per_frame"], 544_400)
        self.assertEqual(vector["per_node_channel_groups_and_tail_slots"]["padded_slots"], 5_728)
        self.assertEqual(vector["per_node_channel_groups_and_tail_slots"]["invalid_tail_slots"], 213)
        self.assertEqual(vector["cycles_per_frame_min_max"], [7_621_600, 8_710_400])
        self.assertEqual(vector["ms_per_frame_at_assumed_200mhz_min_max"], [38.108, 43.552])
        self.assertFalse(vector["target_30fps"])
        self.assertIn("UNKNOWN", vector["full_model_tables_still_need_storage_or_reload"])

    def test_pipeline_and_ddr_are_explicit_unimplemented_assumptions(self):
        candidates = self.contract["throughput_candidates"]
        pipe = candidates["retimed_context_interleaved_lookup_hypothesis"]
        self.assertFalse(pipe["implemented"])
        self.assertEqual(pipe["assumed_reads_per_result_min_max"], [7, 8])
        self.assertEqual(pipe["required_read_ports_for_30fps_requant_only"]["best_path_min_ports"], 16)
        self.assertEqual(pipe["required_read_ports_for_30fps_requant_only"]["worst_path_max_ports"], 18)
        serial_after_private_issue = pipe["required_read_ports_if_serial_after_private_32x4x8_issue"]
        self.assertEqual(serial_after_private_issue["best_path_min_ports"], 49)
        self.assertEqual(serial_after_private_issue["worst_path_max_ports"], 56)
        self.assertEqual(serial_after_private_issue["private_32x4x8_issue_ms_not_measured"], 22.971999999999998)
        self.assertIn("not a RAMB18 instance count", pipe["port_count_definition"])
        self.assertIn("UNKNOWN", pipe["physical_bank_count_and_conflict_free_issue"])
        ddr = candidates["ddr_backed_tables"]
        self.assertEqual(ddr["tightly_bitpacked_33bit_read_bytes_per_frame_min_max"], [418_722_150, 478_539_600])
        self.assertEqual(ddr["five_byte_container_read_bytes_per_frame_min_max"], [507_542_000, 580_048_000])
        self.assertIn("UNKNOWN", ddr["access_latency_and_burst_efficiency"])
        self.assertFalse(self.contract["acceptance_gates"]["30fps_proven"])

    def test_nonconvolution_tables_preserve_exact_add_semantics(self):
        ops = self.contract["nonconvolution_lookup_storage"]
        self.assertEqual(ops["silu"]["nodes"], 57)
        self.assertEqual(ops["silu"]["packaged_table_bytes"], 14_592)
        self.assertEqual(ops["add"]["nodes"], 6)
        self.assertEqual(ops["add"]["candidate_table_bytes"], 393_216)
        load = self.contract["full_graph_residency"]["candidate_weight_and_lookup_payload_once_per_model"]
        self.assertEqual(load["bytes"], 10_690_162)
        self.assertEqual(load["threshold_bytes_assumed"], 7_004_050)
        self.assertIn("not generated", load["threshold_container_status"])
        self.assertEqual(load["actual_generated_int64_threshold_bytes_excluded"], 11_206_480)
        self.assertEqual(ops["add"]["activation_source_ports_per_output"], 2)
        self.assertEqual(ops["add"]["table_read_ports_per_output"], 1)
        self.assertTrue(ops["add"]["two_independent_rescale_then_add_is_not_equivalent"])
        self.assertTrue(ops["add"]["exact_2d_table_not_generated_or_implemented"])
        self.assertIn("UNKNOWN", ops["lookup_ports_and_nonconv_compute_cycles"])

    def test_hand_calculated_geometry_lane_tails_and_bad_assumptions(self):
        toy = threshold_geometry(channels=33)
        self.assertEqual(toy["per_channel_bits"], 8_382)
        self.assertEqual(toy["raw_bits_tightly_packed"], 276_606)
        self.assertEqual(toy["raw_bytes_tightly_packed"], 34_576)
        self.assertEqual(toy["bytes_if_each_channel_byte_aligned"], 34_584)
        self.assertEqual(toy["single_contiguous_ramb18_blocks_at_33x512"], 17)
        self.assertEqual(toy["independent_channel_ramb18_blocks_at_36x512"], 33)
        self.assertEqual(lane_grouping([32, 1]), {
            "lanes": 32, "groups": 2, "valid_channels": 33, "padded_slots": 64,
            "invalid_tail_slots": 31, "per_node_tails": [0, 1],
        })
        with self.assertRaises(ValueError):
            threshold_geometry(0)
        with self.assertRaises(ValueError):
            lane_grouping([32, 0])
        with self.assertRaises(ValueError):
            required_ports_for_issue(1, 2, 0)


if __name__ == "__main__":
    unittest.main()
