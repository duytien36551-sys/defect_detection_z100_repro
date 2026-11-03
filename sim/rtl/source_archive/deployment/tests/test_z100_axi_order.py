from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import validate_z100_axi_order as order  # noqa: E402


class AxiContractTests(unittest.TestCase):
    def test_generated_dma_and_slice_are_idless_with_sixteen_outstanding(self) -> None:
        contract = order.parse_axi_contract(
            order.DMA_VHDL.read_text(encoding="utf-8", errors="replace"),
            order.SLICE_VERILOG.read_text(encoding="utf-8", errors="replace"),
        )
        self.assertEqual(contract["interfaces"]["dma_mm2s"], {"num_read_outstanding": 16, "id_width": 0})
        self.assertEqual(contract["interfaces"]["response_slice_s"], {"num_read_outstanding": 16, "id_width": 0})
        self.assertEqual(contract["interfaces"]["response_slice_m"], {"num_read_outstanding": 16, "id_width": 0})
        self.assertFalse(contract["dma_mm2s_ports_have_arid_rid"])

    def test_missing_dma_interface_attribute_fails_closed(self) -> None:
        dma = order.DMA_VHDL.read_text(encoding="utf-8", errors="replace")
        slice_text = order.SLICE_VERILOG.read_text(encoding="utf-8", errors="replace")
        damaged = dma.replace("ATTRIBUTE X_INTERFACE_PARAMETER OF m_axi_mm2s_araddr", "ATTRIBUTE X_INTERFACE_PARAMETER OF broken_port", 1)
        with self.assertRaises(order.EvidenceError):
            order.parse_axi_contract(damaged, slice_text)

    def test_duplicate_dma_interface_attribute_fails_closed(self) -> None:
        dma = order.DMA_VHDL.read_text(encoding="utf-8", errors="replace")
        slice_text = order.SLICE_VERILOG.read_text(encoding="utf-8", errors="replace")
        start = dma.index("  ATTRIBUTE X_INTERFACE_PARAMETER OF m_axi_mm2s_araddr")
        end = dma.index(";", start) + 1
        duplicate = dma[start:end]
        with self.assertRaises(order.EvidenceError):
            order.parse_axi_contract(dma[:end] + "\n" + duplicate + dma[end:], slice_text)

    def test_id_width_change_fails_closed(self) -> None:
        dma = order.DMA_VHDL.read_text(encoding="utf-8", errors="replace")
        slice_text = order.SLICE_VERILOG.read_text(encoding="utf-8", errors="replace")
        changed = dma.replace("ID_WIDTH 0", "ID_WIDTH 1", 1)
        with self.assertRaises(order.EvidenceError):
            order.parse_axi_contract(changed, slice_text)


class AxiScoreboardTests(unittest.TestCase):
    def test_ordered_multiple_outstanding_trace_passes(self) -> None:
        result = order.validate_scoreboard(
            order._synthetic_trace(), total_words=4, burst_words=2, required_peak=2
        )
        self.assertEqual(result["accepted_before_first_r"], 2)

    def test_reordered_response_is_rejected(self) -> None:
        events = order._synthetic_trace()
        first_r = next(i for i, event in enumerate(events) if event["kind"] == "R")
        events[first_r]["seq"] = 1
        with self.assertRaises(order.EvidenceError):
            order.validate_scoreboard(events, total_words=4, burst_words=2, required_peak=2)

    def test_nonexistent_id_is_rejected(self) -> None:
        events = order._synthetic_trace()
        events[0]["id"] = "0"
        with self.assertRaises(order.EvidenceError):
            order.validate_scoreboard(events, total_words=4, burst_words=2, required_peak=2)

    def test_insufficient_positive_activity_is_rejected(self) -> None:
        with self.assertRaises(order.EvidenceError):
            order.validate_scoreboard(
                order._synthetic_trace(), total_words=4, burst_words=2, required_peak=3
            )

    def test_malformed_log_line_is_rejected(self) -> None:
        with self.assertRaises(order.EvidenceError):
            order.parse_trace_lines("AXI_ORDER_R seq=broken")


if __name__ == "__main__":
    unittest.main()
