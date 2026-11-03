#!/usr/bin/env python3
"""Build and validate an isolated guarded resident-parameter candidate.

This verifies helper protocol behavior, one-cycle completion capture, and
full MMIO source elaboration. It does not run a numeric Conv event, Vivado,
hardware, or performance measurement.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "deployment/hardware/z100_2026"
OLD_DIR = HW / "native_conv_backend_v3_resident"
NEW_DIR = HW / "native_conv_backend_v3_resident_guard_v2"
OLD_HELPER = OLD_DIR / "z100_parameter_residency_v1.sv"
OLD_TB = OLD_DIR / "tb_z100_parameter_residency_v1.sv"
OLD_BACKEND = OLD_DIR / "z100_native_conv_backend_v3_resident.sv"
OLD_WRAPPER = HW / "native_conv_mmio_backend_resident_v1/z100_native_conv_mmio_backend_resident_v1.sv"
BASE_MANIFEST = HW / "native_conv_backend_v3/source_manifest.json"
PARAMETER_READER = HW / "native_parameter_reader_v1/z100_native_parameter_reader.sv"
MMIO_FRONTEND = HW / "native_conv_mmio_v2/z100_native_conv_mmio_v2.sv"
VENDOR = Path(r"C:/appload/2026.1/Vivado/data/verilog/src")
LOCAL = ROOT / "deployment/build/local_tools/iverilog13_msys2/ucrt64"
EVIDENCE_ROOT = ROOT / "validation/board_z100/native_conv_backend_v3_resident_guard_v2"
BUILD_ROOT = ROOT / "deployment/build/native_conv_backend_v3_resident_guard_v2"

PINNED = {
    OLD_HELPER: "e6e2d3daeffab7914bbffe0955c685a5d0dfde5b7d5d54cda81179f3ed910531",
    OLD_TB: "4f98df70457fb32c1433358138e7dbff2647d086e8572e0caefd562b95d4b101",
    OLD_BACKEND: "7d4ddc2d1fcedca02f6aae6b3ffae3e8c0b8eaa38405cc45c3de2e8cc9c3ee30",
    OLD_WRAPPER: "da5a426df61993f2c3dd46bee9df2bd0b761697cd801dabf2bdaF4512c22259f".lower(),
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one {label} anchor; found {text.count(old)}")
    return text.replace(old, new, 1)


def run(argv: list[str], cwd: Path, log: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=str(cwd), text=True, encoding="utf-8",
                            errors="replace", stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    log.write_text(result.stdout, encoding="utf-8")
    return result


def generate_testbench(source: str) -> str:
    tb = replace_once(source, "module tb_z100_parameter_residency_v1;",
                      "module tb_z100_parameter_residency_guard_v2;", "testbench module")
    tb = replace_once(tb, "z100_parameter_residency_v1 dut (.*);",
                      "z100_parameter_residency_guard_v2 dut (.*);", "helper instance")
    tb = replace_once(tb, "Z100_PARAMETER_RESIDENCY_V1_PASS",
                      "Z100_PARAMETER_RESIDENCY_GUARD_V2_PASS", "pass marker")
    tb = replace_once(tb, "Z100_PARAMETER_RESIDENCY_V1_FAIL",
                      "Z100_PARAMETER_RESIDENCY_GUARD_V2_FAIL", "failure marker")
    tb = replace_once(
        tb,
        "check(done_valid && done_error && !downstream_done_ready,\n"
        "              \"error completion respects consumer backpressure\");",
        "check(done_valid && done_error && downstream_done_ready,\n"
        "              \"error pulse is captured while consumer backpressures\");",
        "pulse-source completion acceptance expectation",
    )
    marker = "        if (failures != 0)\n"
    pulse_cases = r'''        // The integrated native_parameter_reader exposes a one-cycle done
        // pulse and has no ready input.  Capture it even when tile_control is
        // stalled, then retain the completion identity and result.
        reset_case();
        issue(16'd4, 1);
        done_ready = 0;
        present_completion(16'd4, 0);
        check(done_valid && downstream_done_ready,
              "one-cycle producer completion accepted while consumer stalls");
        @(posedge clk);
        #1;
        downstream_done_valid = 0;
        downstream_done_error = 0;
        repeat (3) begin
            @(posedge clk);
            #1;
            check(done_valid && !done_error && done_job == 16'd4 &&
                  !downstream_done_valid && !downstream_done_ready,
                  "captured one-cycle completion remains pending");
        end
        done_ready = 1;
        @(posedge clk);
        #1;
        check(!done_valid, "captured completion retires after consumer accepts");
        issue(16'd4, 0);
        check(done_valid && !done_error,
              "successful captured completion populates resident cache");
        @(posedge clk);
        #1;
        check(!done_valid, "resident hit retires once");

        // A one-cycle failed completion is also retained while stalled, but
        // must not leave a cache hit behind.
        reset_case();
        issue(16'd4, 1);
        done_ready = 0;
        present_completion(16'd4, 1);
        check(done_valid && done_error && downstream_done_ready,
              "failed one-cycle producer completion is accepted");
        @(posedge clk);
        #1;
        downstream_done_valid = 0;
        downstream_done_error = 0;
        repeat (2) begin
            @(posedge clk);
            #1;
            check(done_valid && done_error && done_job == 16'd4,
                  "failed completion error remains pending");
        end
        done_ready = 1;
        @(posedge clk);
        #1;
        check(!done_valid, "failed completion retires after consumer accepts");
        issue(16'd4, 1);
        cancel = 1;
        @(posedge clk);
        #1;
        cancel = 0;
        check(!active && !done_valid,
              "failed completion did not create a resident cache hit");

        // Cancellation after a success pulse was captured suppresses the
        // logical completion and invalidates the cache. The native backend
        // separately waits for its AXI readers/writer to drain before quiet.
        reset_case();
        issue(16'd4, 1);
        done_ready = 0;
        present_completion(16'd4, 0);
        @(posedge clk);
        #1;
        downstream_done_valid = 0;
        downstream_done_error = 0;
        check(done_valid && !downstream_done_valid,
              "success pulse is pending before cancellation");
        cancel = 1;
        #1 check(!done_valid && !downstream_done_ready && !cmd_ready &&
                 !downstream_cmd_valid,
                 "cancel suppresses buffered completion publication");
        @(posedge clk);
        #1;
        cancel = 0;
        done_ready = 1;
        check(!active && !done_valid,
              "cancel clears pending logical completion");
        issue(16'd4, 1);
        cancel = 1;
        @(posedge clk);
        #1;
        cancel = 0;

'''
    if tb.count(marker) != 1:
        raise RuntimeError("completion test insertion marker is missing or duplicated")
    tb = tb.replace(marker, pulse_cases + marker, 1)
    if tb.count("Z100_PARAMETER_RESIDENCY_GUARD_V2_PASS") != 1:
        raise RuntimeError("guard-v2 pass marker not generated")
    return tb


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    evidence = EVIDENCE_ROOT / stamp
    build = BUILD_ROOT / stamp
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    NEW_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "schema": "z100-native-parameter-residency-guard-v2/1",
        "status": "RUNNING",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "board_access": False,
        "vivado_run": False,
        "synthesis_or_route_accepted": False,
        "numeric_conv_event_run": False,
        "full_graph_or_30fps_accepted": False,
        "scope": "helper protocol simulation, native one-cycle done integration audit, and full resident-MMIO Icarus elaboration",
        "limits": [
            "helper simulation uses a one-cycle lower completion pulse, not a full parameter-loader transaction",
            "full native backend is elaborated but its Conv datapath is not numerically simulated in this run",
            "no Vivado synthesis, routing, timing, physical DDR, board, or FPS evidence",
        ],
        "commands": [],
        "issues": [],
    }
    inputs = [OLD_HELPER, OLD_TB, OLD_BACKEND, OLD_WRAPPER, BASE_MANIFEST,
              PARAMETER_READER, MMIO_FRONTEND, Path(__file__).resolve()]
    before = {rel(p): sha(p) for p in inputs if p.is_file()}
    try:
        for path, expected in PINNED.items():
            if not path.is_file() or sha(path) != expected:
                raise RuntimeError(f"source pin mismatch: {path}")
        manifest = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
        if manifest.get("top") != "z100_native_conv_backend_v3":
            raise RuntimeError("unexpected V3 manifest top")
        source_map = manifest.get("synthesis_sources")
        if not isinstance(source_map, dict) or len(source_map) != 35:
            raise RuntimeError("expected reviewed 35-file V3 source closure")

        backend_text = OLD_BACKEND.read_text(encoding="utf-8")
        backend_text = replace_once(backend_text,
                                   "module z100_native_conv_backend_v3_resident #(",
                                   "module z100_native_conv_backend_v3_resident_guard_v2 #(\n",
                                   "resident backend module")
        backend_text = replace_once(backend_text,
                                   "z100_parameter_residency_v1 parameter_residency (",
                                   "z100_parameter_residency_guard_v2 parameter_residency (",
                                   "residency helper instance")
        backend_path = NEW_DIR / "z100_native_conv_backend_v3_resident_guard_v2.sv"
        backend_path.write_text(backend_text, encoding="utf-8", newline="\n")

        wrapper_text = OLD_WRAPPER.read_text(encoding="utf-8")
        wrapper_text = replace_once(wrapper_text,
                                    "module z100_native_conv_mmio_backend_resident_v1 #(",
                                    "module z100_native_conv_mmio_backend_resident_guard_v2 #(\n",
                                    "resident wrapper module")
        wrapper_text = replace_once(wrapper_text,
                                    "z100_native_conv_backend_v3_resident #(",
                                    "z100_native_conv_backend_v3_resident_guard_v2 #(",
                                    "resident backend binding")
        wrapper_path = NEW_DIR / "z100_native_conv_mmio_backend_resident_guard_v2.sv"
        wrapper_path.write_text(wrapper_text, encoding="utf-8", newline="\n")

        tb_text = generate_testbench(OLD_TB.read_text(encoding="utf-8"))
        tb_path = NEW_DIR / "tb_z100_parameter_residency_guard_v2.sv"
        tb_path.write_text(tb_text, encoding="utf-8", newline="\n")
        helper_path = NEW_DIR / "z100_parameter_residency_guard_v2.sv"
        for path in (helper_path, backend_path, wrapper_path, tb_path):
            if not path.is_file():
                raise RuntimeError(f"candidate source missing: {path}")

        old_top_name = next(name for name in source_map
                            if name.replace("\\", "/").endswith(
                                "native_conv_backend_v3/z100_native_conv_backend_v3.sv"))
        compile_sources: list[Path] = []
        for raw, expected in source_map.items():
            source = ROOT / Path(raw.replace("\\", "/"))
            if source == ROOT / Path(old_top_name.replace("\\", "/")):
                source = backend_path
            elif not source.is_file() or sha(source) != expected:
                raise RuntimeError(f"base source changed or missing: {source}")
            compile_sources.append(source)
        compile_sources.append(helper_path)
        rom_assets = []
        for raw, expected in manifest.get("rom_assets", {}).items():
            source = ROOT / Path(raw.replace("\\", "/"))
            if not source.is_file() or sha(source) != expected:
                raise RuntimeError(f"ROM asset changed or missing: {source}")
            rom_assets.append({"path": rel(source), "sha256": sha(source)})

        parameter_reader_text = PARAMETER_READER.read_text(encoding="utf-8")
        resident_backend_text = OLD_BACKEND.read_text(encoding="utf-8")
        drain_text = resident_backend_text[resident_backend_text.index("assign all_io_quiet ="):]
        integration_checks = {
            "parameter_loader_done_is_single_cycle_pulse": "output reg done" in parameter_reader_text and
                "done<=0;" in parameter_reader_text and "else begin done<=1;state<=IDLE;end" in parameter_reader_text,
            "native_backend_connects_loader_pulse_to_residency": ".done(parameter_done)" in resident_backend_text and
                ".downstream_done_valid(parameter_done)" in resident_backend_text,
            "residency_done_ready_is_not_loader_ready": ".downstream_done_ready" not in parameter_reader_text,
            "cancel_reaches_parameter_loader_and_residency": ".abort(datapath_cancel)" in resident_backend_text and
                ".clk(clk), .rst_n(rst_n), .cancel(datapath_cancel)," in resident_backend_text,
            "quiet_waits_for_parameter_directory_and_physical_io": all(
                token in drain_text.split(";", 1)[0] for token in
                ("!directory_reader_busy", "!parameter_reader_busy", "!physical_active", "!output_writer_busy")),
            "fault_drain_uses_real_quiet_fence": "assign needs_drain = fault && !all_io_quiet;" in drain_text,
            "v2_backend_uses_guarded_helper": "z100_parameter_residency_guard_v2 parameter_residency" in backend_text,
            "v2_wrapper_selects_guarded_backend": "z100_native_conv_backend_v3_resident_guard_v2 #(" in wrapper_text,
        }
        report["native_integration_checks"] = integration_checks
        if not all(integration_checks.values()):
            raise RuntimeError("native completion/cancel/drain integration audit failed")

        compiler = LOCAL / "bin/iverilog.exe"
        vvp = LOCAL / "bin/vvp.exe"
        lib = LOCAL / "lib/ivl"
        vendor = [VENDOR / "unisims/DSP48E1.v", VENDOR / "unimacro/MULT_MACRO.v", VENDOR / "glbl.v"]
        if any(not p.is_file() for p in [compiler, vvp, *vendor]):
            raise RuntimeError("pinned Icarus or Vivado simulation primitive is missing")

        helper_binary = build / "residency_guard_v2.vvp"
        cmd = [str(compiler), "-B", str(lib), "-g2012", "-Wall", "-s",
               "tb_z100_parameter_residency_guard_v2", "-o", str(helper_binary),
               str(helper_path), str(tb_path)]
        compiled = run(cmd, ROOT, evidence / "helper_compile.log")
        report["commands"].append({"name": "helper_compile", "argv": cmd,
                                   "return_code": compiled.returncode})
        if compiled.returncode != 0 or not helper_binary.is_file():
            raise RuntimeError("guarded helper testbench compilation failed")
        sim = run([str(vvp), str(helper_binary)], ROOT, evidence / "helper_simulation.log")
        report["commands"].append({"name": "helper_simulation",
                                   "argv": [str(vvp), str(helper_binary)],
                                   "return_code": sim.returncode})
        if sim.returncode != 0 or sim.stdout.count("Z100_PARAMETER_RESIDENCY_GUARD_V2_PASS") != 1:
            raise RuntimeError("guarded helper protocol test failed")
        report["helper_simulation_output"] = sim.stdout.strip()

        wrapper_sources = [*compile_sources, MMIO_FRONTEND, wrapper_path, *vendor]
        wrapper_binary = build / "resident_mmio_guard_v2.vvp"
        cmd = [str(compiler), "-B", str(lib), "-g2012", "-Wall", "-s",
               "z100_native_conv_mmio_backend_resident_guard_v2", "-s", "glbl",
               "-o", str(wrapper_binary), *map(str, wrapper_sources)]
        elaborated = run(cmd, NEW_DIR, evidence / "full_mmio_elaboration.log")
        report["commands"].append({"name": "full_mmio_elaboration", "argv": cmd,
                                   "return_code": elaborated.returncode})
        if elaborated.returncode != 0 or not wrapper_binary.is_file() or re.search(
                r"error:|unknown module type|unable to bind|no function named", elaborated.stdout, re.I):
            raise RuntimeError("full resident-MMIO guarded source elaboration failed")

        candidate_manifest = {
            "schema": "z100-native-conv-resident-guard-v2/1",
            "status": "LOCAL_PROTOCOL_AND_ELABORATION_ONLY",
            "tops": {
                "helper": "z100_parameter_residency_guard_v2",
                "backend": "z100_native_conv_backend_v3_resident_guard_v2",
                "mmio": "z100_native_conv_mmio_backend_resident_guard_v2",
            },
            "base_manifest": rel(BASE_MANIFEST),
            "base_v3_rtl_count": len(source_map),
            "base_v3_roms": rom_assets,
            "sources": {
                rel(helper_path): sha(helper_path), rel(tb_path): sha(tb_path),
                rel(backend_path): sha(backend_path), rel(wrapper_path): sha(wrapper_path),
                rel(MMIO_FRONTEND): sha(MMIO_FRONTEND),
            },
            "completion_behavior": "lower one-cycle pulse is accepted into a pending register; upstream valid and request identity stay stable until done_ready",
            "cancel_drain_contract": "cancel discards the logical helper transaction; the native backend readers/writer retain AXI ownership and all_io_quiet remains false until they drain",
            "not_accepted": report["limits"],
        }
        (NEW_DIR / "source_manifest_guard_v2.json").write_text(
            json.dumps(candidate_manifest, indent=2) + "\n", encoding="utf-8")
        report["candidate_manifest"] = rel(NEW_DIR / "source_manifest_guard_v2.json")
        report["source_counts"] = {"v3_rtl": len(source_map),
                                    "helper_closure_rtl": len(compile_sources),
                                    "mmio_elaboration_sources": len(wrapper_sources)}
        report["status"] = "PASS_HELPER_PROTOCOL_AND_MMIO_ELABORATION_ONLY"
    except Exception as exc:  # preserve all evidence on failure
        report["status"] = "FAIL_CLOSED"
        report["issues"] = [f"{type(exc).__name__}: {exc}"]
    after = {rel(p): sha(p) for p in inputs if p.is_file()}
    report["source_sha256_before"] = before
    report["source_sha256_after"] = after
    report["original_inputs_unchanged"] = before == after
    report["candidate_sha256"] = {
        rel(p): sha(p) for p in NEW_DIR.glob("*") if p.is_file()
    }
    report["artifact_sha256"] = {
        rel(p): sha(p) for p in evidence.glob("*") if p.is_file()
    }
    (evidence / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": rel(evidence / "result.json"),
                      "issues": report["issues"]}, indent=2))
    return 0 if report["status"] == "PASS_HELPER_PROTOCOL_AND_MMIO_ELABORATION_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
