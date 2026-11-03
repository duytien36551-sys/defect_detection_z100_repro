"""Run exact Z100 primitive reference miters with a declared reset-time TB input prelude."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "deployment/build/local_tools/iverilog13_msys2"
PREPARED = ROOT / "validation/board_z100/native_primitive_refs/20261026T003636.384545Z/result.json"
PAIR_PROOF = ROOT / "validation/board_z100/int8_pair_packing_v3/20261024T044617.750422Z/result.json"
ACCUM_PROOF = ROOT / "validation/board_z100/accum33_dsp_v2/20261024T051501.085372Z/result.json"
DIAGNOSTIC = ROOT / "validation/board_z100/accum_icarus_diagnostic/20261026T013442.186605Z/result.json"
REFERENCE = ROOT / "deployment/simulation/native_primitive_ref/z100_native_primitive_ref.sv"
REFERENCE_RUNNER = ROOT / "tools/validate_z100_native_primitive_refs.py"
VENDOR = Path("C:/appload/2026.1/Vivado/data/verilog/src")
DSP48E1 = VENDOR / "unisims/DSP48E1.v"
MULT_MACRO = VENDOR / "unimacro/MULT_MACRO.v"
GLBL = VENDOR / "glbl.v"
PRELUDE = "initial begin #0.001; delta=-19'sd1; #0.001; delta=0; end"
ERROR_RE = re.compile(
    r"(?:^\s*(?:ERROR:|FATAL:)|\berror:|\bsorry:|syntax error|"
    r"unable to bind|attribute syntax error|\$fatal)",
    re.IGNORECASE | re.MULTILINE,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_key(path: Path) -> str:
    path = path.resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return "external/" + path.as_posix().replace(":", "")


def resolve_source_key(name: str) -> Path:
    parts = Path(name).parts
    if parts and parts[0] == "external":
        return Path(parts[1] + ":/", *parts[2:])
    return ROOT / Path(name)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_report(path: Path, expected_status: str) -> dict[str, object]:
    report = json.loads(path.read_text(encoding="utf-8"))
    require(report.get("status") == expected_status, f"Prerequisite status {path.name}")
    before = report.get("source_sha256_before")
    after = report.get("source_sha256_after")
    require(isinstance(before, dict) and before == after, f"Stable prerequisite hashes {path.name}")
    for name, expected in {**after, **report.get("artifact_sha256", {})}.items():
        source = resolve_source_key(name)
        require(source.is_file() and sha(source) == expected, f"Prerequisite source/artifact hash {name}")
    return report


def runtime_files() -> tuple[list[Path], dict[str, object]]:
    manifest_path = LOCAL / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("schema") == "project-local-iverilog/1", "Pinned Icarus runtime manifest")
    require(manifest.get("versions", {}).get("iverilog", "").startswith("Icarus Verilog version 13.0"), "Icarus 13.0 runtime")
    files = manifest.get("files", {})
    require(bool(files), "Pinned Icarus runtime files listed")
    paths = [manifest_path]
    for relative, expected in files.items():
        source = LOCAL / Path(relative.replace("\\", "/"))
        require(source.is_file() and sha(source) == expected, f"Icarus runtime manifest hash {relative}")
        paths.append(source)
    return paths, manifest


def miter_literal(name: str) -> str:
    parsed = ast.parse(REFERENCE_RUNNER.read_text(encoding="utf-8"), filename=str(REFERENCE_RUNNER))
    for node in parsed.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            value = ast.literal_eval(node.value)
            require(isinstance(value, str), f"Original {name} miter is a literal string")
            return value
    raise ValueError(f"Original {name} miter not found")


def build_prepared_miter(kind: str, tb: Path, top: str, minimum: int,
                         prepared: dict[str, object], build: Path) -> Path:
    original = tb.read_text(encoding="utf-8")
    require(original.count(top) == 1, f"Unique original {kind} testbench module name")
    require(original.count("endmodule") == 1 and original.count("$finish;") == 1,
            f"Single original {kind} testbench miter seam")
    body = miter_literal("PAIR" if kind == "pair" else "ACCUM")
    result = original.replace(top, top + "_fast_miter")
    result = result.replace("endmodule", body + "\nendmodule")
    result = result.replace(
        "$finish;",
        f'if(fast_checks<{minimum})$fatal(1,"Fast reference miter coverage");'
        f'$display("FAST_REFERENCE_MITER_PASS kind={kind} checks=%0d",fast_checks);$finish;',
    )
    target = build / f"{top}_fast_miter.sv"
    target.write_text(result, encoding="utf-8")
    old_artifacts = prepared.get("artifact_sha256", {})
    expected = next((digest for name, digest in old_artifacts.items() if Path(name).name == target.name), None)
    require(expected is not None and sha(target) == expected, f"Exact prepared {kind} reference miter source")
    return target


def icarus_copy(prepared: Path, top: str, build: Path, add_prelude: bool) -> Path:
    source = prepared.read_text(encoding="utf-8")
    declaration = "integer fast_checks=0;"
    header = f"module {top}_fast_miter;\n"
    require(source.count(declaration) == 1 and source.count(header) == 1, f"Unique {top} miter counter/header")
    normalized_source = source.replace(declaration, "", 1)
    injected = declaration + "\n"
    result = source.replace(declaration, "", 1)
    result = result.replace(header, header + injected, 1)
    normalized = result.replace(header + injected, header, 1)
    if add_prelude:
        require(result.count("endmodule") == 1, f"Single {top} final endmodule")
        result = result.replace("endmodule", PRELUDE + "\nendmodule", 1)
        normalized = result.replace(PRELUDE + "\nendmodule", "endmodule", 1)
        normalized = normalized.replace(header + injected, header, 1)
    require(normalized == normalized_source, f"{top} Icarus copy has only declaration hoist and allowed prelude")
    target = build / f"{top}_fast_miter_icarus.sv"
    target.write_text(result, encoding="utf-8")
    return target


def execute(label: str, args: list[Path | str], out: Path, build: Path, env: dict[str, str],
            commands: list[dict[str, object]], timeout: int, allow_runtime_failure: bool = False) -> str:
    argv = [str(arg) for arg in args]
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=build, env=env, text=True, encoding="utf-8", errors="replace",
                              capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        (out / f"{label}.log").write_text(stdout + ("\n" if stdout and stderr else "") + stderr, encoding="utf-8")
        commands.append({"name": label, "argv": argv, "return_code": None,
                         "wall_seconds": round(time.monotonic() - started, 3), "timeout_seconds": timeout})
        raise ValueError(f"{label} timed out after {timeout}s") from exc
    log = proc.stdout + ("\n" if proc.stdout and proc.stderr else "") + proc.stderr
    (out / f"{label}.log").write_text(log, encoding="utf-8")
    commands.append({"name": label, "argv": argv, "return_code": proc.returncode,
                     "wall_seconds": round(time.monotonic() - started, 3)})
    if "iverilog" in label:
        require(proc.returncode == 0 and ERROR_RE.search(log) is None, f"Strict {label} compilation")
    elif not allow_runtime_failure:
        require(proc.returncode == 0 and ERROR_RE.search(log) is None, f"Strict {label} runtime")
    return log


def parse_numeric_marker(log: str, marker: str, description: str) -> dict[str, int]:
    matches = re.findall(r"^" + re.escape(marker) + r" (.+)$", log, re.MULTILINE)
    require(len(matches) == 1, f"Exactly one {description} marker")
    values = dict(re.findall(r"(\w+)=(-?\d+)", matches[0]))
    return {name: int(value) for name, value in values.items()}


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = ROOT / "validation/board_z100/native_primitive_refs_iverilog_v2" / stamp
    build = ROOT / "build" / f"nprf_ivl_v2_{stamp[-14:]}"
    out.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    report_path = out / "result.json"
    sources: list[Path] = []
    before: dict[str, str] = {}
    report: dict[str, object] = {
        "schema": "z100-native-primitive-refs-iverilog-v2/1",
        "status": "RUNNING",
        "commands": [],
        "board_access": False,
        "simulation_references_only": True,
        "startup_input_prelude": True,
        "startup_input_prelude_text": PRELUDE,
        "exact_original_startup_pass": False,
        "production_dut_modified": False,
        "vendor_source_modified": False,
        "force_initialization_used": False,
        "full_pipeline_30fps_accepted": False,
        "vendor_sources": [str(DSP48E1), str(MULT_MACRO), str(GLBL)],
        "diagnostic_prerequisite": source_key(DIAGNOSTIC),
    }

    try:
        prepared = verify_report(PREPARED, "PREPARED_SIMULATION_ONLY_PRIMITIVE_MITERS_NOT_EXECUTED")
        pair_proof = verify_report(PAIR_PROOF, "PASS_PRIVATE_EXACT_SIGNED_PAIR_HOST_XSIM_ONE_DSP_OOC_ONLY")
        accum_proof = verify_report(ACCUM_PROOF, "PASS_PRIVATE_SIGNED33_FEEDBACK_XSIM_ONE_DSP_OOC_ONLY")
        diagnostic = verify_report(DIAGNOSTIC, "DIAGNOSTIC_CAPTURED_ORIGINAL_ACCUM_MISMATCH")
        require(diagnostic.get("force_initialization_used") is False, "Diagnostic prerequisite used no force initialization")
        require(diagnostic.get("vendor_source_modified") is False, "Diagnostic prerequisite left vendor sources unchanged")
        pair_sim = pair_proof.get("simulation", {})
        accum_sim = accum_proof.get("simulation", {})
        require(pair_sim == {
            "status": "PASS", "inputs": 1110260, "output_pairs": 1110258,
            "consecutive_ii1": 1048576, "bubbles": 3870, "reset_cancel_flushes": 2, "latency": 1,
        }, "Original pair-suite XSIM proof counters")
        require(accum_sim == {
            "status": "PASS", "checks": 16754, "loads": 64, "updates": 16528,
            "holds": 145, "flushes": 17, "saturations": 4087, "consecutive_ii1": 1024, "latency": 1,
        }, "Original accumulator XSIM proof counters")

        pair_module = ROOT / "deployment/hardware/z100_2026/int8_pair_packing_v3/z100_int8_pair_packing.sv"
        pair_tb = ROOT / "deployment/hardware/z100_2026/int8_pair_packing_v3/tb_z100_int8_pair_packing.sv"
        accum_module = ROOT / "deployment/hardware/z100_2026/accum33_dsp_v2/z100_accum33_dsp.sv"
        accum_tb = ROOT / "deployment/hardware/z100_2026/accum33_dsp_v2/tb_z100_accum33_dsp.sv"
        pair_base = build_prepared_miter("pair", pair_tb, "tb_z100_int8_pair_packing", 1048576, prepared, build)
        accum_base = build_prepared_miter("accum", accum_tb, "tb_z100_accum33_dsp", 16700, prepared, build)
        pair_icarus = icarus_copy(pair_base, "tb_z100_int8_pair_packing", build, add_prelude=False)
        accum_icarus = icarus_copy(accum_base, "tb_z100_accum33_dsp", build, add_prelude=True)

        local_runtime, manifest = runtime_files()
        binary = LOCAL / "ucrt64/bin"
        backend = LOCAL / "ucrt64/lib/ivl"
        iverilog = binary / "iverilog.exe"
        vvp = binary / "vvp.exe"
        require(all(path.exists() for path in (iverilog, vvp, backend, DSP48E1, MULT_MACRO, GLBL)),
                "Pinned simulator and actual installed vendor sources available")

        sources = [
            Path(__file__), PREPARED, PAIR_PROOF, ACCUM_PROOF, DIAGNOSTIC,
            REFERENCE_RUNNER, REFERENCE, pair_module, pair_tb, accum_module, accum_tb,
            pair_base, accum_base, pair_icarus, accum_icarus, DSP48E1, MULT_MACRO, GLBL,
            *local_runtime,
        ]
        before = dict(sorted((source_key(path), sha(path)) for path in sources))
        report.update(
            source_sha256_before=before,
            prepared_report=source_key(PREPARED),
            original_pair_proof=source_key(PAIR_PROOF),
            original_accum_proof=source_key(ACCUM_PROOF),
            simulator=manifest.get("versions"),
            runtime_manifest=source_key(LOCAL / "manifest.json"),
            runtime_manifest_sha256=sha(LOCAL / "manifest.json"),
            prepared_miter_sha256={source_key(pair_base): sha(pair_base), source_key(accum_base): sha(accum_base)},
            icarus_miter_sha256={source_key(pair_icarus): sha(pair_icarus), source_key(accum_icarus): sha(accum_icarus)},
            scope=(
                "Simulation-only comparison of both unchanged production arithmetic modules and actual installed "
                "Vivado primitive models. The generated accumulator testbench adds only the declared 2ps delta "
                "input prelude while rst_n remains low and before the first clock edge. Original checks and vectors "
                "then run unchanged. This does not validate exact original startup behavior, synthesis, timing, "
                "platform integration, FPGA execution or physical throughput."
            ),
        )
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

        env = dict(os.environ)
        env["PATH"] = str(binary) + os.pathsep + env.get("PATH", "")
        env["OMP_NUM_THREADS"] = "1"
        commands: list[dict[str, object]] = report["commands"]
        version = execute("iverilog_version", [iverilog, "-V"], out, build, env, commands, 30)
        vvp_version = execute("vvp_version", [vvp, "-V"], out, build, env, commands, 30)
        require(manifest["versions"]["iverilog"] in version, "Icarus executable matches runtime manifest")
        require("Icarus Verilog runtime version 13.0" in vvp_version, "VVP runtime matches pinned version")

        pair_binary = build / "pair_fast_miter.vvp"
        accum_binary = build / "accum_fast_miter.vvp"
        pair_compile = [iverilog, "-B", backend, "-g2012", "-s", "tb_z100_int8_pair_packing_fast_miter", "-s", "glbl",
                        "-o", pair_binary, REFERENCE, MULT_MACRO, DSP48E1, GLBL, pair_module, pair_icarus]
        accum_compile = [iverilog, "-B", backend, "-g2012", "-s", "tb_z100_accum33_dsp_fast_miter", "-s", "glbl",
                         "-o", accum_binary, REFERENCE, DSP48E1, GLBL, accum_module, accum_icarus]
        pair_compile_log = execute("pair_iverilog", pair_compile, out, build, env, commands, 120)
        accum_compile_log = execute("accum_iverilog", accum_compile, out, build, env, commands, 120)
        pair_log = execute("pair_vvp", [vvp, "-M", backend, pair_binary], out, build, env, commands, 180)
        accum_log = execute("accum_vvp", [vvp, "-M", backend, accum_binary], out, build, env, commands, 60)

        pair_marker = parse_numeric_marker(pair_log, "INT8_PAIR_PACKING_PASS", "original pair suite")
        require(pair_marker == {
            "inputs": 1110260, "outputs": 1110258, "ii1_streak": 1048576,
            "bubbles": 3870, "flushes": 2, "latency": 1, "signed_edge": -128,
        }, "Exact original pair-suite counters")
        pair_checks = re.findall(r"^FAST_REFERENCE_MITER_PASS kind=pair checks=(\d+)$", pair_log, re.MULTILINE)
        require(len(pair_checks) == 1 and int(pair_checks[0]) == pair_marker["inputs"],
                "Pair post-NBA reference comparisons cover every accepted input")
        require(len(re.findall(r"\$finish called at", pair_log)) == 1, "Pair suite reached one original finish")

        accum_marker = parse_numeric_marker(accum_log, "ACCUM33_DSP_PASS", "original accumulator suite")
        require(accum_marker == {
            "checks": 16754, "loads": 64, "updates": 16528, "holds": 145,
            "flushes": 17, "saturations": 4087, "ii1_streak": 1024,
        }, "Exact original accumulator-suite counters after declared prelude")
        accum_checks = re.findall(r"^FAST_REFERENCE_MITER_PASS kind=accum checks=(\d+)$", accum_log, re.MULTILINE)
        require(len(accum_checks) == 1 and int(accum_checks[0]) >= 16700, "Accumulator reference comparison coverage")
        require(len(re.findall(r"\$finish called at", accum_log)) == 1, "Accumulator suite reached one original finish")

        report.update(
            status="PASS_ICARUS_VENDOR_REFERENCE_MITERS_RESET_INPUT_PRELUDE_SIMULATION_ONLY",
            miters=[{"kind": "pair", "checks": int(pair_checks[0])},
                    {"kind": "accum", "checks": int(accum_checks[0])}],
            original_suite_counters={"pair": pair_marker, "accum": accum_marker},
            diagnostics={
                "pair_compile_warnings": len(re.findall(r"\bwarning:", pair_compile_log, re.I)),
                "accum_compile_warnings": len(re.findall(r"\bwarning:", accum_compile_log, re.I)),
            },
            limitations=(
                "The accepted simulation harness includes a legal reset-time delta input prelude to initialize the "
                "installed Icarus DSP48E1 model's event-driven A mux chain. Exact original startup without this "
                "prelude still fails in Icarus and is recorded separately. The prelude does not establish mapped "
                "resources, timing, FPGA behavior or physical FPS."
            ),
        )
    except Exception as exc:
        report.update(status="FAILED_CLOSED", error=f"{type(exc).__name__}: {exc}")

    try:
        if sources:
            after = dict(sorted((source_key(path), sha(path)) for path in sources))
            report["source_sha256_before"] = before
            report["source_sha256_after"] = after
            if before != after:
                report.update(status="FAILED_SOURCE_INTEGRITY", error="Bound source/vendor/runtime changed during run")
        report["artifact_sha256"] = {
            source_key(path): sha(path)
            for folder in (out, build)
            for path in folder.rglob("*")
            if path.is_file() and path != report_path
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        report.update(status="FAILED_REPORT_FINALIZATION", error=f"{type(exc).__name__}: {exc}")
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"status": report["status"], "report": source_key(report_path), "error": report.get("error")}))
    return 0 if str(report["status"]).startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
