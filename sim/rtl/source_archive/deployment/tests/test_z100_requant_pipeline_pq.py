from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import validate_z100_requant_pipeline_pq as validator


def module_text(source: str, name: str) -> str:
    start = source.index(f"module {name} (")
    end = source.index("endmodule", start) + len("endmodule")
    return source[start:end]


class RequantPipelinePQTests(unittest.TestCase):
    def test_p_and_q_are_structurally_isomorphic_except_read_register_ownership(self):
        source = (ROOT / "deployment/hardware/z100_2026/requant_pipeline_v2/requant_memory_pq.sv").read_text()
        p = module_text(source, "z100_requant_memory_p")
        q = module_text(source, "z100_requant_memory_q")
        for module in (p, q):
            self.assertIn("input  wire [1:0]  cfg_write_enable", module)
            self.assertIn("input  wire [15:0] cfg_write_address", module)
            self.assertIn("input  wire [65:0] cfg_write_data", module)
            self.assertIn("input  wire [1:0]  read_enable", module)
            self.assertIn("input  wire [15:0] read_address", module)
            self.assertIn("output wire [65:0] read_data", module)
            self.assertEqual(module.count("(* ram_style = \"block\" *) reg signed [32:0] tree_mem [0:254];"), 1)
            self.assertEqual(module.count("always @(posedge clk)"), 2)
            self.assertIn("if (!rst_n || cancel)", module)
            self.assertIn("cfg_write_enable[i]", module)
            self.assertIn("cfg_write_address[i*8 +: 8]", module)
            self.assertIn("cfg_write_data[i*33 +: 33]", module)
            self.assertIn("read_enable[i]", module)
            self.assertIn("read_address[i*8 +: 8]", module)
            self.assertNotIn("< 8'd255", module)

        p_normalized = p.replace("module z100_requant_memory_p", "module SAME_TOP")
        q_normalized = q.replace("module z100_requant_memory_q", "module SAME_TOP")
        p_normalized = p_normalized.replace("    reg signed [32:0] key_q [0:1];\n", "")
        p_normalized = p_normalized.replace("key_q[i]", "read_q")
        q_normalized = q_normalized.replace("            reg signed [32:0] read_q;\n", "")
        p_normalized = p_normalized.replace(");\n\n    genvar", ");\n    genvar")
        self.assertEqual(p_normalized, q_normalized)

    def test_actual_cell_parser_attributes_ram_cells_and_pin_connections_by_gen(self):
        output = """Vivado v2026.1 (64-bit) Build 6511674
synth_design completed successfully
PQSUMMARY|P|z100_requant_memory_p|LUT=12|FF=0|RAMB18=2|RAMB36=0|DSP=0|PERIOD_NS=5.000
PQGEN|P|0|LUT=6|FF=0|RAMB18=1|RAMB36=0|DSP=0
PQGEN|P|1|LUT=6|FF=0|RAMB18=1|RAMB36=0|DSP=0
PQUNATTRIBUTED|P|LUT=12-6-6|FF=0-0-0|RAMB18=2-1-1|RAMB36=0-0-0|DSP=0-0-0
PQRAM|P|0|z100_requant_memory_p/gen_pair[0].tree_mem_reg|RAMB18E1
PQRAM|P|1|z100_requant_memory_p/gen_pair[1].tree_mem_reg|RAMB18E1
PQPIN|P|0|z100_requant_memory_p/gen_pair[0].tree_mem_reg|ADDRARDADDR[0]|net0|read_address[0]|U0/A
PQPIN|P|0|z100_requant_memory_p/gen_pair[0].tree_mem_reg|DIADI[0]|net1|cfg_write_data[0]|U0/B
PQPIN|P|0|z100_requant_memory_p/gen_pair[0].tree_mem_reg|WEA[0]|net2|cfg_write_enable[0]|U0/C
PQPIN|P|0|z100_requant_memory_p/gen_pair[0].tree_mem_reg|ENARDEN|net3|read_enable[0]|U0/D
PQPIN|P|0|z100_requant_memory_p/gen_pair[0].tree_mem_reg|CLKARDCLK|net4|clk|U0/E
PQPIN|P|0|z100_requant_memory_p/gen_pair[0].tree_mem_reg|DOADO[0]|net5|read_data[0]|U0/F
PQPIN|P|1|z100_requant_memory_p/gen_pair[1].tree_mem_reg|ADDRARDADDR[0]|net6|read_address[8]|U1/A
PQPIN|P|1|z100_requant_memory_p/gen_pair[1].tree_mem_reg|DIBDI[0]|net7|cfg_write_data[33]|U1/B
PQPIN|P|1|z100_requant_memory_p/gen_pair[1].tree_mem_reg|WEBWE[0]|net8|cfg_write_enable[1]|U1/C
PQPIN|P|1|z100_requant_memory_p/gen_pair[1].tree_mem_reg|ENBWREN|net9|read_enable[1]|U1/D
PQPIN|P|1|z100_requant_memory_p/gen_pair[1].tree_mem_reg|CLKARDCLK|net10|clk|U1/E
PQPIN|P|1|z100_requant_memory_p/gen_pair[1].tree_mem_reg|DOBDO[0]|net11|read_data[33]|U1/F
"""
        utilization = """|          Instance         | Module | Total LUTs | Logic LUTs | LUTRAMs | SRLs | FFs | RAMB36 | RAMB18 | DSP Blocks |
| z100_requant_memory_p    | (top)  |        12 |        12 |       0 |    0 |   0 |      0 |      2 |          0 |
"""
        parsed = validator.parse_variant(output, utilization, "P")
        self.assertEqual(parsed["global_counts"]["ramb18_equivalent"], 2)
        self.assertEqual(parsed["generations"]["0"]["ramb18_equivalent"], 1)
        self.assertEqual(parsed["generations"]["1"]["ramb18_equivalent"], 1)
        self.assertEqual(len(parsed["physical_ram_cells"]), 2)
        self.assertEqual(len(parsed["ram_input_output_pin_connections"]), 12)

    def test_mapping_classification_covers_requested_outcomes(self):
        self.assertEqual(validator.classify_mapping({"total_ramb18_equivalent": 0},
                                                    {"total_ramb18_equivalent": 2}), "P_ZERO_Q_MAPPED")
        self.assertEqual(validator.classify_mapping({"total_ramb18_equivalent": 0},
                                                    {"total_ramb18_equivalent": 0}), "P_AND_Q_ZERO")
        self.assertEqual(validator.classify_mapping({"total_ramb18_equivalent": 1},
                                                    {"total_ramb18_equivalent": 1}), "P_AND_Q_MAPPED")

    def test_synthesis_tcl_is_ooc_synth_only_and_records_cell_pins(self):
        with tempfile.TemporaryDirectory() as temp_root:
            build = Path(temp_root) / "build"
            validator._write_synth_tcl("P", build)
            script = (build / validator.VARIANTS["P"] / "synth.tcl").read_text()
        self.assertIn("synth_design -top z100_requant_memory_p", script)
        self.assertIn("-flatten_hierarchy none", script)
        self.assertIn("PQGEN|P|$lane", script)
        self.assertIn("PQRAM|P|$lane", script)
        self.assertIn("get_pins -quiet -of_objects $cell", script)
        self.assertIn("ADDR|DI|WE|EN|CLK|DO", script)
        self.assertNotIn("route_design", script)
        self.assertNotIn("write_bitstream", script)


if __name__ == "__main__":
    unittest.main()
