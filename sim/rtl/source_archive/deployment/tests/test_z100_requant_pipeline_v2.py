from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import validate_z100_requant_pipeline_v2 as validator


class RequantPipelineV2ABTests(unittest.TestCase):
    def test_metrics_parse_per_top_and_compute_ram18_equivalent(self):
        text = "REQUANT_MEMORY_AB top=z100_requant_memory_norst LUT=210 FF=80 RAMB18=1 RAMB36=2 DSP=0 PERIOD_NS=5.000"
        metrics = validator.parse_metrics(text, "z100_requant_memory_norst")
        self.assertEqual(metrics["ramb18_equivalent"], 5)
        self.assertEqual(metrics["dsp"], 0)

    def test_hierarchical_utilization_parser_uses_per_top_counts(self):
        text = """|          Instance         | Module | Total LUTs | Logic LUTs | LUTRAMs | SRLs | FFs | RAMB36 | RAMB18 | DSP Blocks |
| z100_requant_memory_norst | (top)  |        18 |        18 |       0 |    0 |  33 |      0 |      1 |          0 |
"""
        counts = validator.parse_hierarchical_utilization(text, "z100_requant_memory_norst")
        self.assertEqual(counts, dict(total_luts=18, logic_luts=18, lutrams=0, srls=0,
                                      flip_flops=33, ramb36=0, ramb18=1, dsp=0))

    def test_full_v2_budget_is_fixed_and_bounded(self):
        passing = dict(slice_lut=2048, flip_flops=2048, ramb18_equivalent=8, dsp=0)
        self.assertTrue(validator.resource_budget_passes(passing))
        self.assertFalse(validator.resource_budget_passes({**passing, "slice_lut": 2049}))
        self.assertFalse(validator.resource_budget_passes({**passing, "flip_flops": 2049}))
        self.assertFalse(validator.resource_budget_passes({**passing, "ramb18_equivalent": 0}))
        self.assertFalse(validator.resource_budget_passes({**passing, "ramb18_equivalent": 9}))
        self.assertFalse(validator.resource_budget_passes({**passing, "dsp": 1}))

    def test_ab_variants_keep_identical_memory_ports_and_change_only_read_data_reset(self):
        source = (ROOT / "deployment/hardware/z100_2026/requant_pipeline_v2/requant_memory_ab.sv").read_text()
        self.assertEqual(source.count("reg [32:0] table_mem [0:254];"), 2)
        self.assertEqual(source.count("cfg_write_enable && cfg_write_address < 8'd255"), 2)
        self.assertEqual(source.count("read_enable && read_address < 8'd255"), 2)
        self.assertIn("if (!rst_n || cancel)\n            read_data <= 33'd0;", source)
        self.assertIn("if (rst_n && !cancel && read_enable && read_address < 8'd255)", source)


if __name__ == "__main__":
    unittest.main()
