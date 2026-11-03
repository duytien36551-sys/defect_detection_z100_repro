"""Host checks for the isolated full-pipeline RAM-wrapper experiment."""
from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import validate_z100_requant_pipeline as baseline  # noqa: E402

RTL = ROOT / "deployment/hardware/z100_2026/requant_pipeline_ram_wrapper_v1/z100_requant_pipeline_ram_wrapper.sv"
BASE_RTL = ROOT / "deployment/hardware/z100_2026/requant_pipeline_v1/z100_requant_pipeline.sv"


class RequantRamWrapperTests(unittest.TestCase):
    def test_original_full_fixture_reference_has_11264_vectors(self) -> None:
        rows, tables, _proof = baseline._read_reference()
        self.assertEqual(len(rows), 5515)
        self.assertEqual(len(tables), 5515)
        self.assertEqual(len(baseline._synthetic_tables()), 3)
        self.assertEqual(baseline.CASE_COUNT * baseline.VECTORS_PER_CASE, 11264)

    def test_wrapper_preserves_the_v1_top_level_port_declarations(self) -> None:
        def header(path: Path, module: str) -> str:
            text = path.read_text(encoding="utf-8")
            match = re.search(rf"module\s+{module}\s*\((.*?)\);", text, re.S)
            if not match:
                self.fail(f"missing module declaration: {module}")
            return re.sub(r"\s+", " ", match.group(1)).strip()

        self.assertEqual(
            header(BASE_RTL, "z100_requant_pipeline"),
            header(RTL, "z100_requant_pipeline_ram_wrapper"),
        )

    def test_each_search_stage_owns_a_scalar_ram_wrapper_and_wire_read_output(self) -> None:
        text = RTL.read_text(encoding="utf-8")
        self.assertIn("wire signed [32:0] key_q [0:7];", text)
        self.assertEqual(text.count("z100_requant_table_scalar u_table"), 1)
        self.assertIn("for (i = 0; i < 8; i = i + 1) begin : gen_search", text)
        self.assertIn('(* ram_style = "block" *) reg signed [32:0] tree_mem [0:254];', text)
        self.assertIn("read_q <= tree_mem[rd_addr];", text)
        self.assertRegex(text, r"if\s*\(!rst_n\s*\|\|\s*cancel\)\s*read_q\s*<=\s*33'sd0")
        self.assertIn(".rd_data(key_q[i])", text)
        self.assertNotRegex(text, r"rd_addr\s*<\s*8'd255")
        self.assertEqual(text.count("always @(posedge clk)"), 3)


if __name__ == "__main__":
    unittest.main()
