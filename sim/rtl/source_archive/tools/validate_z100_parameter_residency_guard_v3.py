#!/usr/bin/env python3
"""Build and validate an isolated command-scoped guard-v3 candidate."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "deployment/hardware/z100_2026"
V2 = HW / "native_conv_backend_v3_resident_guard_v2"
V3 = HW / "native_conv_backend_v3_resident_guard_v3"
V2_HELPER = V2 / "z100_parameter_residency_guard_v2.sv"
V2_TB = V2 / "tb_z100_parameter_residency_guard_v2.sv"
V2_BACKEND = V2 / "z100_native_conv_backend_v3_resident_guard_v2.sv"
V2_WRAPPER = V2 / "z100_native_conv_mmio_backend_resident_guard_v2.sv"
V2_MANIFEST = V2 / "source_manifest_guard_v2.json"
BASE_MANIFEST = HW / "native_conv_backend_v3/source_manifest.json"
EVENT_CONTROL = HW / "conv_event_v1/z100_conv_event_control.sv"
ROM_PREFETCH = HW / "conv_rom_prefetch_v2/z100_conv_rom_prefetch_v2.sv"
PARAMETER_READER = HW / "native_parameter_reader_v1/z100_native_parameter_reader.sv"
MMIO_FRONTEND = HW / "native_conv_mmio_v2/z100_native_conv_mmio_v2.sv"
VENDOR = Path("C:/appload/2026.1/Vivado/data/verilog/src")
LOCAL = ROOT / "deployment/build/local_tools/iverilog13_msys2/ucrt64"
EVIDENCE_ROOT = ROOT / "validation/board_z100/native_conv_backend_v3_resident_guard_v3"
BUILD_ROOT = ROOT / "deployment/build/native_conv_backend_v3_resident_guard_v3"

PINNED_V2 = {
    V2_HELPER: "9e58d3048e45cc70fedc3c29f76669661fd9ac33c66455070140422c36080617",
    V2_TB: "8448f0347c55a04b58a4857630056bd003ebbf9dc4329824ee448b1ffa6eb3fd",
    V2_BACKEND: "a72706f31f5e453e3b36c5dd79321db89ba560c51aa3b5f290118f14c3aba751",
    V2_WRAPPER: "5d723b31b79c6913e9903d8a666b759e0b7f1d74eb818c14b9ffbe600b607d82",
}


def sha(path: Path) -> str:
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


def run(argv: list[str], cwd: Path, log: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=str(cwd), text=True, encoding="utf-8",
                            errors="replace", stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    log.write_text(result.stdout, encoding="utf-8")
    return result


def generate_helper(source: str) -> str:
    text = replace_once(source,
                        "module z100_parameter_residency_guard_v2 (",
                        "module z100_parameter_residency_guard_v3 (", "helper module")
    text = replace_once(text, "    input  wire        cancel,\n",
                        "    input  wire        cancel,\n"
                        "    input  wire        outer_command_start,\n", "boundary port")
    text = replace_once(text,
                        "wire idle = state == ST_IDLE && rst_n && !cancel && !fault &&\n",
                        "wire idle = state == ST_IDLE && rst_n && !cancel &&\n"
                        "        !outer_command_start && !fault &&\n", "boundary handshake mask")
    text = replace_once(text, "        end else if (state == ST_FAULT) begin\n",
                        "        end else if (outer_command_start) begin\n"
                        "            // Asserted with the accepted outer backend command.\n"
                        "            // Parameter requests must not own the guard at this boundary.\n"
                        "            cache_valid <= 1'b0;\n"
                        "            pending_error <= 1'b0;\n"
                        "            if (state != ST_IDLE) begin\n"
                        "                state <= ST_FAULT;\n"
                        "                fault <= 1'b1;\n"
                        "                fault_code <= 3'd4;\n"
                        "            end else if (downstream_done_valid) begin\n"
                        "                state <= ST_FAULT;\n"
                        "                fault <= 1'b1;\n"
                        "                fault_code <= 3'd1;\n"
                        "            end\n"
                        "        end else if (state == ST_FAULT) begin\n",
                        "boundary invalidation priority")
    text = replace_once(text,
                        "assign downstream_done_ready = state == ST_WAIT && rst_n && !cancel && !fault;",
                        "assign downstream_done_ready = state == ST_WAIT && rst_n && !cancel &&\n"
                        "        !outer_command_start && !fault;",
                        "boundary completion-ready mask")
    text = replace_once(text,
                        "assign done_valid = rst_n && !cancel && !fault &&\n",
                        "assign done_valid = rst_n && !cancel && !outer_command_start && !fault &&\n",
                        "boundary completion-valid mask")
    return text


def generate_backend(source: str) -> str:
    text = replace_once(source,
                        "module z100_native_conv_backend_v3_resident_guard_v2 #(\n",
                        "module z100_native_conv_backend_v3_resident_guard_v3 #(\n",
                        "backend module")
    text = replace_once(text,
                        "z100_parameter_residency_guard_v2 parameter_residency (",
                        "z100_parameter_residency_guard_v3 parameter_residency (",
                        "guard binding")
    return replace_once(text,
                        ".clk(clk), .rst_n(rst_n), .cancel(datapath_cancel),\n"
                        "        .context_valid(context_valid), .context_epoch(event_epoch),",
                        ".clk(clk), .rst_n(rst_n), .cancel(datapath_cancel),\n"
                        "        .outer_command_start(cmd_valid && cmd_ready),\n"
                        "        .context_valid(context_valid), .context_epoch(event_epoch),",
                        "outer accepted-command connection")


def generate_wrapper(source: str) -> str:
    text = replace_once(source,
                        "module z100_native_conv_mmio_backend_resident_guard_v2 #(\n",
                        "module z100_native_conv_mmio_backend_resident_guard_v3 #(\n",
                        "MMIO wrapper module")
    return replace_once(text,
                        "z100_native_conv_backend_v3_resident_guard_v2 #(\n",
                        "z100_native_conv_backend_v3_resident_guard_v3 #(\n",
                        "MMIO backend binding")


def generate_testbench(source: str) -> str:
    text = replace_once(source, "module tb_z100_parameter_residency_guard_v2;",
                        "module tb_z100_parameter_residency_guard_v3;", "testbench module")
    text = replace_once(text,
                        "reg rst_n = 0, cancel = 0, context_valid = 1;",
                        "reg rst_n = 0, cancel = 0, context_valid = 1;\n"
                        "    reg outer_command_start = 0;", "boundary test signal")
    text = replace_once(text, "z100_parameter_residency_guard_v2 dut (.*);",
                        "z100_parameter_residency_guard_v3 dut (.*);", "helper instance")
    text = replace_once(text, "Z100_PARAMETER_RESIDENCY_GUARD_V2_PASS",
                        "Z100_PARAMETER_RESIDENCY_GUARD_V3_PASS", "pass marker")
    text = replace_once(text, "Z100_PARAMETER_RESIDENCY_GUARD_V2_FAIL",
                        "Z100_PARAMETER_RESIDENCY_GUARD_V3_FAIL", "failure marker")
    text = replace_once(text, "            cancel = 0;\n            cmd_valid = 0;",
                        "            cancel = 0;\n"
                        "            outer_command_start = 0;\n"
                        "            cmd_valid = 0;", "reset boundary input")
    task_anchor = "    task present_completion(input [15:0] job, input error);\n"
    task_lines = [
        "    task begin_outer_command;",
        "        begin",
        "            @(negedge clk);",
        "            check(!active, \"outer boundary requires idle residency guard\");",
        "            outer_command_start = 1;",
        "            #1;",
        "            check(!cmd_ready && !downstream_cmd_valid,",
        "                  \"outer boundary masks parameter handshakes\");",
        "            @(posedge clk);",
        "            #1;",
        "            outer_command_start = 0;",
        "            check(!active && !fault, \"outer boundary clears resident cache\");",
        "        end",
        "    endtask",
        "",
    ]
    text = replace_once(text, task_anchor, "\n".join(task_lines) + task_anchor,
                        "outer boundary test task")
    marker = "        if (failures != 0)\n"
    cases = [
        "        // Cache reuse is valid inside one outer command; the next accepted",
        "        // outer command with the same key must reload its parameter job.",
        "        reset_case();",
        "        begin_outer_command();",
        "        issue(16'd4, 1);",
        "        complete_downstream(16'd4, 0);",
        "        issue(16'd4, 0);",
        "        check(done_valid && !done_error,",
        "              \"same outer command reuses its newly loaded parameter job\");",
        "        @(posedge clk);",
        "        #1;",
        "        check(!done_valid, \"same-command resident hit retires once\");",
        "",
        "        begin_outer_command();",
        "        issue(16'd4, 1);",
        "        complete_downstream(16'd4, 0);",
        "        issue(16'd4, 0);",
        "        check(done_valid && !done_error,",
        "              \"second outer command reloads then reuses the same key\");",
        "        @(posedge clk);",
        "        #1;",
        "        check(!done_valid, \"second-command resident hit retires once\");",
        "",
        "        // Illegal outer boundaries must suppress an old hit completion.",
        "        reset_case();",
        "        issue(16'd4, 1);",
        "        complete_downstream(16'd4, 0);",
        "        done_ready = 1;",
        "        issue(16'd4, 0);",
        "        check(done_valid, \"hit owner is pending before illegal boundary\");",
        "        @(negedge clk);",
        "        outer_command_start = 1;",
        "        #1;",
        "        check(!done_valid && !cmd_ready && !downstream_cmd_valid,",
        "              \"boundary masks same-cycle resident-hit publication\");",
        "        @(posedge clk);",
        "        #1;",
        "        outer_command_start = 0;",
        "        check(fault && fault_code == 3'd4, \"hit boundary violation faults\");",
        "        cancel = 1;",
        "        @(posedge clk);",
        "        #1;",
        "        cancel = 0;",
        "",
        "        // The same suppression applies to a buffered completion while the",
        "        // tile consumer is stalled; it must not transfer at the boundary.",
        "        reset_case();",
        "        issue(16'd4, 1);",
        "        done_ready = 0;",
        "        present_completion(16'd4, 0);",
        "        @(posedge clk);",
        "        #1;",
        "        downstream_done_valid = 0;",
        "        downstream_done_error = 0;",
        "        done_ready = 1;",
        "        check(done_valid, \"buffered owner is pending before illegal boundary\");",
        "        @(negedge clk);",
        "        outer_command_start = 1;",
        "        #1;",
        "        check(!done_valid && !downstream_done_ready,",
        "              \"boundary suppresses buffered valid and completion ready\");",
        "        @(posedge clk);",
        "        #1;",
        "        outer_command_start = 0;",
        "        check(fault && fault_code == 3'd4, \"pending boundary violation faults\");",
        "        cancel = 1;",
        "        @(posedge clk);",
        "        #1;",
        "        cancel = 0;",
        "",
        "        // A one-cycle lower done pulse must not be acknowledged on an",
        "        // illegal outer boundary that overlaps an active miss.",
        "        reset_case();",
        "        issue(16'd4, 1);",
        "        present_completion(16'd4, 0);",
        "        outer_command_start = 1;",
        "        #1;",
        "        check(!done_valid && !downstream_done_ready,",
        "              \"boundary suppresses lower pulse publication and acceptance\");",
        "        @(posedge clk);",
        "        #1;",
        "        outer_command_start = 0;",
        "        downstream_done_valid = 0;",
        "        check(fault && fault_code == 3'd4, \"miss boundary violation faults\");",
        "        cancel = 1;",
        "        @(posedge clk);",
        "        #1;",
        "        cancel = 0;",
        "",
        "        // The backend cannot accept a new outer command while a parameter",
        "        // request owns the helper. Exercise fail-closed behavior directly.",
        "        reset_case();",
        "        issue(16'd4, 1);",
        "        @(negedge clk);",
        "        outer_command_start = 1;",
        "        @(posedge clk);",
        "        #1;",
        "        outer_command_start = 0;",
        "        check(fault && fault_code == 3'd4,",
        "              \"outer boundary during active parameter owner faults closed\");",
        "        cancel = 1;",
        "        @(posedge clk);",
        "        #1;",
        "        cancel = 0;",
        "        check(!active && !fault, \"cancel retires illegal boundary owner\");",
        "",
    ]
    return replace_once(text, marker, "\n".join(cases) + marker,
                        "command-scoped tests")


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    evidence = EVIDENCE_ROOT / stamp
    build = BUILD_ROOT / stamp
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    V3.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "schema": "z100-native-parameter-residency-guard-v3/1",
        "status": "RUNNING",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "board_access": False,
        "vivado_run": False,
        "synthesis_or_route_accepted": False,
        "numeric_conv_event_run": False,
        "full_graph_or_30fps_accepted": False,
        "scope": "unchanged V2 regression, command-scoped V3 helper simulation, source boundary audit, and full MMIO Icarus elaboration",
        "limits": [
            "outer command boundary is modeled at the helper interface, not a full backend transaction",
            "real native_parameter_reader transaction/backpressure/cancel is not dynamically simulated",
            "no Conv numeric simulation, Vivado implementation, physical DDR, board, or FPS evidence",
        ],
        "commands": [],
        "issues": [],
    }
    candidate_paths: list[Path] = []
    inputs: list[Path] = [V2_HELPER, V2_TB, V2_BACKEND, V2_WRAPPER, V2_MANIFEST,
                          BASE_MANIFEST, EVENT_CONTROL, ROM_PREFETCH,
                          PARAMETER_READER, MMIO_FRONTEND, Path(__file__).resolve()]
    try:
        for path, expected in PINNED_V2.items():
            if not path.is_file() or sha(path) != expected:
                raise RuntimeError(f"guard-v2 source pin mismatch: {path}")
        base = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
        sources = base.get("synthesis_sources")
        if base.get("top") != "z100_native_conv_backend_v3" or not isinstance(sources, dict) or len(sources) != 35:
            raise RuntimeError("unexpected base V3 source closure")
        inputs.extend(ROOT / Path(raw.replace("\\", "/")) for raw in sources)
        rom_assets = []
        for raw, expected in base.get("rom_assets", {}).items():
            asset = ROOT / Path(raw.replace("\\", "/"))
            if not asset.is_file() or sha(asset) != expected:
                raise RuntimeError(f"base ROM changed or missing: {asset}")
            rom_assets.append({"path": rel(asset), "sha256": sha(asset)})
            inputs.append(asset)
        before = {rel(path): sha(path) for path in inputs if path.is_file()}

        helper = V3 / "z100_parameter_residency_guard_v3.sv"
        tb = V3 / "tb_z100_parameter_residency_guard_v3.sv"
        backend = V3 / "z100_native_conv_backend_v3_resident_guard_v3.sv"
        wrapper = V3 / "z100_native_conv_mmio_backend_resident_guard_v3.sv"
        helper.write_text(generate_helper(V2_HELPER.read_text(encoding="utf-8")),
                          encoding="utf-8", newline="\n")
        tb.write_text(generate_testbench(V2_TB.read_text(encoding="utf-8")),
                      encoding="utf-8", newline="\n")
        backend_text = generate_backend(V2_BACKEND.read_text(encoding="utf-8"))
        backend.write_text(backend_text, encoding="utf-8", newline="\n")
        wrapper_text = generate_wrapper(V2_WRAPPER.read_text(encoding="utf-8"))
        wrapper.write_text(wrapper_text, encoding="utf-8", newline="\n")
        candidate_paths = [helper, tb, backend, wrapper]

        backend_v2_text = V2_BACKEND.read_text(encoding="utf-8")
        event_text = EVENT_CONTROL.read_text(encoding="utf-8")
        rom_text = ROM_PREFETCH.read_text(encoding="utf-8")
        reader_text = PARAMETER_READER.read_text(encoding="utf-8")
        helper_text = helper.read_text(encoding="utf-8")
        integration_checks = {
            "outer_cmd_ready_independent_of_residency": "assign cmd_ready = event_cmd_ready && command_resources_valid && !cancel && !fault;" in backend_v2_text,
            "event_rom_accepts_only_while_idle": "state_q==ST_IDLE && !fault_q && !cancel" in rom_text,
            "outer_event_completion_waits_for_quiet": "state_q==ST_DRAIN && controller_done" in rom_text and "if (all_io_quiet && load_quiet && tile_write_quiet)" in rom_text and "DRAIN:if(io_quiet)" in event_text,
            "outer_handshake_connected_to_guard": ".outer_command_start(cmd_valid && cmd_ready)" in backend_text,
            "boundary_cycle_blocks_parameter_handshake": "!outer_command_start && !fault" in helper_text and "!outer_command_start && !fault" in helper_text[helper_text.index("assign downstream_done_ready"):helper_text.index("assign done_epoch")],
            "boundary_cycle_blocks_upstream_completion": "!outer_command_start && !fault" in helper_text[helper_text.index("assign done_valid"):helper_text.index("assign done_epoch")],
            "active_boundary_fails_closed": "if (state != ST_IDLE) begin" in helper_text and "fault_code <= 3'd4;" in helper_text,
            "native_loader_done_is_single_cycle_pulse": "output reg done" in reader_text and "done<=0;" in reader_text and "else begin done<=1;state<=IDLE;end" in reader_text,
            "native_loader_pulse_connected": ".done(parameter_done)" in backend_v2_text and ".downstream_done_valid(parameter_done)" in backend_v2_text,
            "quiet_fence_covers_parameter_and_physical_readers": all(token in backend_v2_text[backend_v2_text.index("assign all_io_quiet ="):].split(";", 1)[0] for token in ("!directory_reader_busy", "!parameter_reader_busy", "!physical_active", "!output_writer_busy")),
        }
        report["outer_command_atomicity_checks"] = integration_checks
        if not all(integration_checks.values()):
            raise RuntimeError("could not establish atomic outer command invalidation boundary")

        compiler = LOCAL / "bin/iverilog.exe"
        vvp = LOCAL / "bin/vvp.exe"
        lib = LOCAL / "lib/ivl"
        vendor = [VENDOR / "unisims/DSP48E1.v", VENDOR / "unimacro/MULT_MACRO.v", VENDOR / "glbl.v"]
        if any(not path.is_file() for path in [compiler, vvp, *vendor]):
            raise RuntimeError("pinned Icarus or Vivado simulation primitive is missing")

        # Run the unchanged V2 regression into V3-owned evidence/build paths.
        v2_binary = build / "guard_v2_protocol.vvp"
        command = [str(compiler), "-B", str(lib), "-g2012", "-Wall", "-s",
                   "tb_z100_parameter_residency_guard_v2", "-o", str(v2_binary),
                   str(V2_HELPER), str(V2_TB)]
        result = run(command, ROOT, evidence / "guard_v2_compile.log")
        report["commands"].append({"name": "guard_v2_protocol_compile", "argv": command, "return_code": result.returncode})
        if result.returncode != 0 or not v2_binary.is_file():
            raise RuntimeError("unchanged V2 protocol test did not compile")
        result = run([str(vvp), str(v2_binary)], ROOT, evidence / "guard_v2_simulation.log")
        report["commands"].append({"name": "guard_v2_protocol_simulation", "argv": [str(vvp), str(v2_binary)], "return_code": result.returncode})
        if result.returncode != 0 or result.stdout.count("Z100_PARAMETER_RESIDENCY_GUARD_V2_PASS") != 1:
            raise RuntimeError("unchanged V2 protocol regression failed")
        report["guard_v2_simulation_output"] = result.stdout.strip()

        v3_binary = build / "guard_v3_protocol.vvp"
        command = [str(compiler), "-B", str(lib), "-g2012", "-Wall", "-s",
                   "tb_z100_parameter_residency_guard_v3", "-o", str(v3_binary),
                   str(helper), str(tb)]
        result = run(command, ROOT, evidence / "guard_v3_compile.log")
        report["commands"].append({"name": "guard_v3_protocol_compile", "argv": command, "return_code": result.returncode})
        if result.returncode != 0 or not v3_binary.is_file():
            raise RuntimeError("V3 protocol testbench did not compile")
        result = run([str(vvp), str(v3_binary)], ROOT, evidence / "guard_v3_simulation.log")
        report["commands"].append({"name": "guard_v3_protocol_simulation", "argv": [str(vvp), str(v3_binary)], "return_code": result.returncode})
        if result.returncode != 0 or result.stdout.count("Z100_PARAMETER_RESIDENCY_GUARD_V3_PASS") != 1:
            raise RuntimeError("V3 command-scoped protocol tests failed")
        report["guard_v3_simulation_output"] = result.stdout.strip()

        base_top = next(name for name in sources if name.replace("\\", "/").endswith("native_conv_backend_v3/z100_native_conv_backend_v3.sv"))
        compile_sources: list[Path] = []
        for raw, expected in sources.items():
            path = ROOT / Path(raw.replace("\\", "/"))
            if path == ROOT / Path(base_top.replace("\\", "/")):
                path = backend
            elif not path.is_file() or sha(path) != expected:
                raise RuntimeError(f"base source changed or missing: {path}")
            compile_sources.append(path)
        compile_sources.append(helper)
        wrapper_binary = build / "resident_mmio_guard_v3.vvp"
        wrapper_sources = [*compile_sources, MMIO_FRONTEND, wrapper, *vendor]
        command = [str(compiler), "-B", str(lib), "-g2012", "-Wall", "-s",
                   "z100_native_conv_mmio_backend_resident_guard_v3", "-s", "glbl",
                   "-o", str(wrapper_binary), *map(str, wrapper_sources)]
        result = run(command, ROOT, evidence / "full_mmio_elaboration.log")
        report["commands"].append({"name": "full_mmio_elaboration", "argv": command, "return_code": result.returncode})
        if result.returncode != 0 or not wrapper_binary.is_file() or re.search(
                r"error:|unknown module type|unable to bind|no function named", result.stdout, re.I):
            raise RuntimeError("full MMIO guard-v3 source elaboration failed")

        manifest = {
            "schema": "z100-native-conv-resident-guard-v3/1",
            "status": "LOCAL_COMMAND_BOUNDARY_PROTOCOL_AND_ELABORATION_ONLY",
            "tops": {"helper": "z100_parameter_residency_guard_v3",
                     "backend": "z100_native_conv_backend_v3_resident_guard_v3",
                     "mmio": "z100_native_conv_mmio_backend_resident_guard_v3"},
            "base_manifest": rel(BASE_MANIFEST),
            "parent_candidate_manifest": rel(V2_MANIFEST),
            "base_v3_rtl_count": len(sources),
            "base_v3_roms": rom_assets,
            "sources": {rel(path): sha(path) for path in [*candidate_paths, MMIO_FRONTEND]},
            "cache_lifecycle": "invalidate on cmd_valid && cmd_ready at the accepted outer backend command edge; reuse is allowed for tiles within that command; invalidation with an active parameter owner faults closed",
            "outer_command_atomicity_checks": integration_checks,
            "not_accepted": report["limits"],
        }
        manifest_path = V3 / "source_manifest_guard_v3.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        candidate_paths.append(manifest_path)
        report["candidate_manifest"] = rel(manifest_path)
        report["source_counts"] = {"base_v3_rtl": len(sources),
                                   "helper_closure_rtl": len(compile_sources),
                                   "mmio_elaboration_sources": len(wrapper_sources)}
        report["status"] = "PASS_COMMAND_SCOPED_PROTOCOL_AND_MMIO_ELABORATION_ONLY"
    except Exception as exc:
        report["status"] = "FAIL_CLOSED"
        report["issues"] = [f"{type(exc).__name__}: {exc}"]

    after = {rel(path): sha(path) for path in inputs if path.is_file()}
    if "before" in locals():
        report["source_sha256_before"] = before
        report["source_sha256_after"] = after
        report["original_inputs_unchanged"] = before == after
        if before != after and report["status"] != "FAIL_CLOSED":
            report["status"] = "FAIL_CLOSED"
            report["issues"] = ["source input changed during validation"]
    report["candidate_sha256"] = {rel(path): sha(path) for path in candidate_paths if path.is_file()}
    report["artifact_sha256"] = {rel(path): sha(path) for path in evidence.glob("*") if path.is_file()}
    (evidence / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": rel(evidence / "result.json"),
                      "issues": report["issues"]}, indent=2))
    return 0 if report["status"] == "PASS_COMMAND_SCOPED_PROTOCOL_AND_MMIO_ELABORATION_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())

