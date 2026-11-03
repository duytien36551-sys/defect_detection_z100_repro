"""Run a small directed FIFO scoreboard against the free-slot raw-buffer candidate."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re
import sys

import run_z100_staged_packer_core_v2 as v2

core = v2.core
ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "deployment/hardware/z100_2026/raw_buffer_free_slot_capture_v1/z100_native_raw_buffer.sv"
TB = ROOT / "deployment/hardware/z100_2026/raw_buffer_free_slot_capture_v1/tb_z100_native_raw_buffer_free_slot.sv"
OUT_ROOT = ROOT / "validation/board_z100/raw_buffer_free_slot_capture_v1"
BUILD_ROOT = ROOT / "build"


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = OUT_ROOT / stamp
    build = BUILD_ROOT / ("rawbuf_" + stamp.replace(".", ""))
    out.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    report = out / "result.json"
    result = {
        "schema": "z100-raw-buffer-free-slot-scoreboard/1",
        "status": "PREPARING",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "report": core.v12.project_name(report),
        "run_directory": core.v12.project_name(out),
        "build_directory": core.v12.project_name(build),
        "scope": "Two-slot behavioral equivalence for accepted stream items and stall/reset/cancel/full behavior; invalid-slot payload is intentionally unspecified.",
        "source_sha256": {},
        "commands": [],
        "checks": [],
    }
    core.save_json(report, result)
    try:
        core.require(RTL.is_file() and TB.is_file(), "candidate RTL/TB missing")
        core.bind(result["source_sha256"], RTL)
        core.bind(result["source_sha256"], TB)
        core.bind(result["source_sha256"], Path(__file__).resolve())
        core.v12.require_quiescent()
        mutex = core.VendorMutex()
        mutex.acquire()
        try:
            xvlog = core.VENDOR / "xvlog.bat"
            xelab = core.VENDOR / "xelab.bat"
            xsim = core.VENDOR / "xsim.bat"
            core.run_vendor_command(result, "xvlog", [xvlog, "-sv", RTL, TB], build, out / "xvlog.log")
            snapshot = "rawbuf_" + stamp.replace("T", "").replace("Z", "").replace(".", "")
            core.run_vendor_command(result, "xelab", [xelab, "-mt", "2", "-L", "unimacro_ver", "-L", "unisims_ver", TB.stem, "-s", snapshot], build, out / "xelab.log")
            sim = core.run_vendor_command(result, "xsim", [xsim, snapshot, "-runall"], build, out / "xsim.log")
        finally:
            mutex.release()
        markers = re.findall(r"^RAW_BUFFER_FREE_SLOT_PASS .+$", sim, re.M)
        core.require(len(markers) == 1, "missing exact scoreboard PASS marker")
        marker = markers[0]
        fields = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", marker)}
        core.require(fields.get("invalid_payload_changes", 0) > 0, "test did not observe invalid payload changing")
        core.require(fields.get("stall_holds", 0) > 0 and fields.get("pushes", 0) > 0 and fields.get("pops", 0) > 0,
                     "stream scoreboard coverage is vacuous")
        result.update(status="PASS_RAW_BUFFER_ACCEPTED_STREAM_AND_CONTROL_ONLY", pass_marker=marker,
                      semantics="out_data is only asserted against expected data while out_valid=1; while valid && !ready it must remain stable; invalid payload is allowed to change.",
                      board_timing_or_fps_accepted=False)
        result["checks"].append({"check": "two_entry_fifo_scoreboard_and_invalid_payload_scope", "status": "PASS", "coverage": fields})
        result["artifact_sha256"] = core.artifact_hashes(out, build, report)
        result["source_sha256_after"] = {name: core.sha256_file(core.v12.resolve(name)) for name in result["source_sha256"]}
        core.save_json(report, result)
        print(json.dumps({"status": result["status"], "report": result["report"], "pass_marker": marker}))
        return 0
    except Exception as exc:
        result.update(status="FAILED_CLOSED", error=f"{type(exc).__name__}: {exc}")
        result["artifact_sha256"] = core.artifact_hashes(out, build, report)
        core.save_json(report, result)
        print(json.dumps({"status": result["status"], "report": result["report"], "error": result["error"]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
