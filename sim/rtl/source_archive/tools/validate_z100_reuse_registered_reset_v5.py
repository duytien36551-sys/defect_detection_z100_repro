"""Registered reset distribution after the v4 external-reset setup failure."""
from pathlib import Path
import validate_z100_reuse_registered_monitor_v4 as registered

flow = registered.flow
SOURCE = Path(__file__).resolve()
flow.FIXTURE = flow.ROOT / "deployment/hardware/z100_2026/reuse_registered_reset_v5"
flow.RTL = flow.FIXTURE / "z100_tile_reuse_resident_v3.v"
flow.TIMING_TOP = flow.FIXTURE / "z100_tile_reuse_resident_v3_timing_top.sv"
flow.TIMING_TB = flow.FIXTURE / "tb_z100_tile_reuse_resident_v3_timing_top.sv"
flow.CONSTRAINTS = flow.FIXTURE / "resident_v3_constraints.xdc"
flow.TCL = flow.FIXTURE / "dsp_impl_v3.tcl"
flow.BUILD_ROOT = flow.ROOT / "deployment/build/z100_reuse_registered_reset_v5"
flow.EVIDENCE_ROOT = flow.ROOT / "validation/board_z100/reuse_registered_reset_v5"
flow.SOURCES = (flow.RTL, flow.TIMING_TOP, flow.TIMING_TB, flow.SIM_BUFG,
                flow.CONSTRAINTS, flow.TCL, Path(flow.__file__).resolve(),
                Path(registered.__file__).resolve(), SOURCE)

_review = flow.review_outputs


def review_registered_reset(*args):
    result = _review(*args)
    result["candidate_variant"] = "two_register_reset_boundary_v5_registered_serial_v4_frozen_v3_arithmetic"
    result["reset_contract"] = "External active-low reset held for at least two core clocks; assertion/release sampled through two registers. Private timing fixture only."
    return result


flow.review_outputs = review_registered_reset

if __name__ == "__main__":
    raise SystemExit(flow.main())
