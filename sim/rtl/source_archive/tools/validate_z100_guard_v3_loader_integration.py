#!/usr/bin/env python3
"""Run real parameter-loader co-simulation with the command-scoped guard V3.

The v3 testbench is generated as an independent extension of the pinned v2
loader integration harness. It directly stimulates outer_command_start, while
the backend connection to the accepted outer command is checked against RTL.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "deployment/hardware/z100_2026"
V2_TB = HW / "guard_loader_integration_test/tb_z100_guard_parameter_loader_integration.sv"
V3_DIR = HW / "native_conv_backend_v3_resident_guard_v3"
V3_HELPER = V3_DIR / "z100_parameter_residency_guard_v3.sv"
V3_BACKEND = V3_DIR / "z100_native_conv_backend_v3_resident_guard_v3.sv"
V3_MANIFEST = V3_DIR / "source_manifest_guard_v3.json"
LOADER = HW / "native_parameter_reader_v1/z100_native_parameter_reader.sv"
TEST_DIR = HW / "guard_v3_loader_integration_test"
TB = TEST_DIR / "tb_z100_guard_v3_parameter_loader_integration.sv"
LOCAL = ROOT / "deployment/build/local_tools/iverilog13_msys2/ucrt64"
EVIDENCE_ROOT = ROOT / "validation/board_z100/guard_v3_loader_integration"
EXPECTED = {
    V2_TB: "5a58bf51e953f37cf06319446d642c7f34bb88c2399133c510fc91e7bd105c2f",
    V3_HELPER: "16f5a1d1a0da98ba8ba0c7842fd08eaaf26af97cdacc2b2570e730fb751e8aa1",
    V3_BACKEND: "f8e57eeb8bb232e2323bdadaf9d161102bd4704bafb1cbe23c001374e53411e1",
    LOADER: "bf6779eded3740c57140526681f0f403964b6c54836076d469a25499bc1914a4",
}
PASS = "Z100_GUARD_V3_PARAMETER_LOADER_INTEGRATION_PASS"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one {label} anchor; found {count}")
    return source.replace(old, new, 1)


def generate_v3_testbench(source: str) -> str:
    tb = replace_once(
        source, "module tb_z100_guard_parameter_loader_integration;",
        "module tb_z100_guard_v3_parameter_loader_integration;", "testbench module",
    )
    tb = replace_once(
        tb, "reg rst_n = 0, abort_loader = 0, cancel_guard = 0;\n",
        "reg rst_n = 0, abort_loader = 0, cancel_guard = 0;\n"
        "    reg outer_command_start = 0;\n", "outer boundary signal",
    )
    tb = replace_once(
        tb, "z100_parameter_residency_guard_v2 residency_guard (",
        "z100_parameter_residency_guard_v3 residency_guard (", "guard instance module",
    )
    tb = replace_once(
        tb, ".clk(clk), .rst_n(rst_n), .cancel(cancel_guard),\n",
        ".clk(clk), .rst_n(rst_n), .cancel(cancel_guard),\n"
        "        .outer_command_start(outer_command_start),\n", "guard boundary port",
    )
    boundary_and_reload = """        // A new accepted outer command invalidates the old resident entry.
        // Present a same-key parameter request on that edge: V3 must mask it,
        // then forward a miss after the boundary pulse has ended.
        @(negedge clk);
        cmd_job = 16'd4;
        cmd_valid = 1;
        outer_command_start = 1;
        #1;
        check(!cmd_ready && !downstream_cmd_valid && !done_valid &&
              !downstream_done_ready,
              \"outer command edge masks parameter command and completion\");
        @(posedge clk);
        #1;
        outer_command_start = 0;
        cmd_valid = 0;
        check(!guard_active && !guard_fault,
              \"idle outer command boundary clears cache without fault\");
        check(loader_job_accepts == 1,
              \"outer boundary itself does not launch parameter loader\");

        // Same key after the boundary is a fresh miss and runs the actual
        // loader again. A second same-key request within this outer command
        // must then hit the newly populated entry.
        issue_command(16'd4, 0);
        finish_stalled_completion();
        check(loader_job_accepts == 2,
              \"same key after new outer command reloads through real loader\");
        check(reader_command_count == 8,
              \"new outer command rereads all four parameter segments\");
        check(cfg_accept_count > 500,
              \"outer-command reload emits the complete config stream again\");
        begin : verify_v3_same_command_hit
            integer accepted_before;
            accepted_before = loader_job_accepts;
            done_ready = 1;
            issue_command(16'd4, 1);
            check(done_valid && !done_error && done_job == 16'd4,
                  \"reloaded same-command job hits V3 resident entry\");
            @(posedge clk);
            #1;
            check(!done_valid, \"V3 same-command hit retires once\");
            done_ready = 0;
            check(loader_job_accepts == accepted_before,
                  \"V3 same-command hit starts no extra loader job\");
        end

"""
    tb = replace_once(
        tb,
        "        // Cancel a second real loader transaction with its reader response\n",
        boundary_and_reload +
        "        // Cancel a second real loader transaction with its reader response\n",
        "outer-command reload insertion point",
    )
    tb = replace_once(
        tb,
        "check(loader_job_accepts == 2, \"replacement never reaches loader before/after cancel\");",
        "check(loader_job_accepts == 3, \"replacement never reaches loader before/after cancel\");",
        "loader transaction total",
    )
    tb = replace_once(
        tb,
        "check(reader_command_count == 5, \"cancelled job owns one additional reader command\");",
        "check(reader_command_count == 9, \"cancelled job owns one additional reader command\");",
        "reader command total",
    )
    tb = replace_once(
        tb, "Z100_GUARD_PARAMETER_LOADER_INTEGRATION_FAIL",
        "Z100_GUARD_V3_PARAMETER_LOADER_INTEGRATION_FAIL", "failure marker",
    )
    tb = replace_once(
        tb, "Z100_GUARD_PARAMETER_LOADER_INTEGRATION_PASS",
        PASS, "pass marker",
    )
    return tb


def run(name: str, argv: list[str], output: Path) -> dict[str, object]:
    try:
        proc = subprocess.run(
            argv, cwd=str(ROOT), text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180,
        )
        output.write_text(proc.stdout, encoding="utf-8")
        return {"name": name, "argv": argv, "return_code": proc.returncode,
                "log": rel(output), "timed_out": False}
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        output.write_text(str(partial) + "\nTIMEOUT after 180 seconds\n", encoding="utf-8")
        return {"name": name, "argv": argv, "return_code": None,
                "log": rel(output), "timed_out": True}


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    evidence = EVIDENCE_ROOT / stamp
    evidence.mkdir(parents=True, exist_ok=False)
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "schema": "z100-guard-v3-parameter-loader-integration/1",
        "status": "RUNNING",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": [
            "actual command-scoped z100_parameter_residency_guard_v3 RTL",
            "actual z100_native_parameter_reader RTL",
            "v2 real-loader integration scenarios copied into an independent v3 testbench",
            "new outer_command_start boundary followed by same-key real-loader reload and same-command hit",
            "static audit that the stable backend connects outer_command_start to cmd_valid && cmd_ready",
        ],
        "coverage": [
            "real loader first config command obeys ready backpressure",
            "actual loader reads all four parameter segments and emits a one-cycle completion",
            "v3 guard holds completion under consumer backpressure",
            "same-command cache hit suppresses a second loader job",
            "outer_command_start masks parameter handshakes and clears the prior cache",
            "same key after outer boundary misses, rereads all four segments, then hits within that command",
            "cancel clears residency while the modeled AXI reader retains ownership until drain",
        ],
        "limits": [
            "AXI read source and configuration bridge are testbench protocol models",
            "quiet fence represents only modeled reader busy, not full backend all_io_quiet",
            "outer_command_start is exercised at the real helper port; backend port connection is statically audited, not full-backend dynamic simulation",
            "directory/content version has no independent key input; this test covers invalidation across outer command starts, not mutations without a boundary",
            "no numeric Conv validation, physical DDR, Vivado implementation, board, full graph, or FPS evidence",
        ],
        "board_access": False,
        "vivado_run": False,
        "commands": [],
        "issues": [],
    }
    try:
        compiler = LOCAL / "bin/iverilog.exe"
        vvp = LOCAL / "bin/vvp.exe"
        lib = LOCAL / "lib/ivl"
        for path in (compiler, vvp, lib, V2_TB, V3_HELPER, V3_BACKEND, V3_MANIFEST, LOADER):
            if not path.exists():
                raise FileNotFoundError(f"required validation input missing: {path}")
        pinned_hashes = {rel(path): sha256(path) for path in EXPECTED}
        for path, expected in EXPECTED.items():
            if pinned_hashes[rel(path)] != expected:
                raise RuntimeError(f"pinned source changed: {rel(path)}")
        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        manifest_sources = manifest.get("sources", {})
        if manifest_sources.get(rel(V3_HELPER)) != pinned_hashes[rel(V3_HELPER)]:
            raise RuntimeError("v3 helper hash does not match stable candidate manifest")
        if manifest_sources.get(rel(V3_BACKEND)) != pinned_hashes[rel(V3_BACKEND)]:
            raise RuntimeError("v3 backend hash does not match stable candidate manifest")
        backend_text = V3_BACKEND.read_text(encoding="utf-8")
        backend_connected = ".outer_command_start(cmd_valid && cmd_ready)" in backend_text
        if not backend_connected:
            raise RuntimeError("stable backend outer command handshake is not connected to V3 guard")
        report["stable_candidate"] = {
            "manifest": rel(V3_MANIFEST),
            "manifest_sha256": sha256(V3_MANIFEST),
            "backend_outer_command_start_connected": backend_connected,
        }
        report["source_sha256"] = pinned_hashes

        tb_source = generate_v3_testbench(V2_TB.read_text(encoding="utf-8"))
        TB.write_text(tb_source, encoding="utf-8", newline="\n")
        report["generated_testbench"] = rel(TB)
        report["generated_testbench_sha256"] = sha256(TB)

        binary = evidence / "guard_v3_parameter_loader_integration.vvp"
        compile_argv = [
            str(compiler), "-B", str(lib), "-g2012", "-Wall", "-s",
            "tb_z100_guard_v3_parameter_loader_integration", "-o", str(binary),
            str(V3_HELPER), str(LOADER), str(TB),
        ]
        compiled = run("compile", compile_argv, evidence / "compile.log")
        report["commands"].append(compiled)
        if compiled["return_code"] != 0 or not binary.is_file():
            raise RuntimeError("Icarus compilation failed")

        sim_argv = [str(vvp), str(binary)]
        simulated = run("simulation", sim_argv, evidence / "simulation.log")
        report["commands"].append(simulated)
        sim_output = (evidence / "simulation.log").read_text(encoding="utf-8")
        report["simulation_output"] = sim_output.strip()
        if (simulated["return_code"] != 0 or simulated["timed_out"] or
                sim_output.count(PASS) != 1 or re.search(r"FAIL |_FAIL", sim_output)):
            raise RuntimeError("v3 parameter loader integration assertions failed")
        report["status"] = "PASS_V3_REAL_LOADER_HARNESS_ONLY"
    except Exception as exc:
        report["status"] = "FAIL_CLOSED"
        report["issues"] = [f"{type(exc).__name__}: {exc}"]

    report["artifact_sha256"] = {
        rel(path): sha256(path) for path in evidence.iterdir() if path.is_file()
    }
    result_path = evidence / "result.json"
    result_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "result": rel(result_path),
                      "issues": report["issues"]}, indent=2))
    return 0 if report["status"] == "PASS_V3_REAL_LOADER_HARNESS_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
