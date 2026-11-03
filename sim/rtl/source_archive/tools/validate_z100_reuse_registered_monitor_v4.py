"""Measure registered serial-output timing fixture over byte-identical v3 arithmetic."""
from pathlib import Path
import validate_z100_reuse_resident_v3 as flow

SOURCE = Path(__file__).resolve()
flow.FIXTURE = flow.ROOT / "deployment/hardware/z100_2026/reuse_registered_monitor_v4"
flow.RTL = flow.FIXTURE / "z100_tile_reuse_resident_v3.v"
flow.TIMING_TOP = flow.FIXTURE / "z100_tile_reuse_resident_v3_timing_top.sv"
flow.TIMING_TB = flow.FIXTURE / "tb_z100_tile_reuse_resident_v3_timing_top.sv"
flow.CONSTRAINTS = flow.FIXTURE / "resident_v3_constraints.xdc"
flow.TCL = flow.FIXTURE / "dsp_impl_v3.tcl"
flow.BUILD_ROOT = flow.ROOT / "deployment/build/z100_reuse_registered_monitor_v4"
flow.EVIDENCE_ROOT = flow.ROOT / "validation/board_z100/reuse_registered_monitor_v4"
flow.SOURCES = (flow.RTL, flow.TIMING_TOP, flow.TIMING_TB, flow.SIM_BUFG,
                flow.CONSTRAINTS, flow.TCL, Path(flow.__file__).resolve(), SOURCE)

_review = flow.review_outputs


def review_registered_outputs(evidence, frequency, expected_hashes, vivado_result):
    result = _review(evidence, frequency, expected_hashes, vivado_result)
    # Vivado get_ports counts75 individual output bits, not8 logical vectors.
    # Keep every numerical/resource/timing/DRC/source check from the common
    # flow; correct only its observable-port census for this independent run.
    observability = (evidence / "synth_observability.txt").read_text(encoding="utf-8")
    topology = (evidence / "routed_clock_topology.txt").read_text(encoding="utf-8")
    result["checks"]["fixture_observability_pass"] = (
        "BLACKBOX_COUNT 0" in observability and "OUTPUT_PORT_COUNT 75" in observability
        and "BUFG_COUNT 1" in topology and "REGISTER_COUNT " in topology)
    passed = all(result["checks"].values()) and not result["drc_review"]["unexpected"]
    result["status"] = (f"PASS_{frequency}MHZ_COMPONENT_TIMING_RESOURCE_DRC_OPEN_UNACCEPTED"
                        if passed else "FAIL_IMPLEMENTATION_REVIEW")
    result["candidate_variant"] = "registered_elastic_serial_output_v4_frozen_v3_arithmetic"
    result["observable_output_bits_required"] = 75
    return result


flow.review_outputs = review_registered_outputs

if __name__ == "__main__":
    raise SystemExit(flow.main())
