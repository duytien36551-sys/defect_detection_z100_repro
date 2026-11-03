"""Run the unchanged Z100 primitive suites and reference miters with Icarus."""
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
REFERENCE = ROOT / "deployment/simulation/native_primitive_ref/z100_native_primitive_ref.sv"
REFERENCE_RUNNER = ROOT / "tools/validate_z100_native_primitive_refs.py"
VENDOR = Path("C:/appload/2026.1/Vivado/data/verilog/src")
DSP48E1 = VENDOR / "unisims/DSP48E1.v"
MULT_MACRO = VENDOR / "unimacro/MULT_MACRO.v"
GLBL = VENDOR / "glbl.v"
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


def sha_map(paths: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in paths:
        result[source_key(path)] = sha(path)
    return dict(sorted(result.items()))


def literal_miter(name: str) -> str:
    tree = ast.parse(REFERENCE_RUNNER.read_text(encoding="utf-8"), filename=str(REFERENCE_RUNNER))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            value = ast.literal_eval(node.value)
            require(isinstance(value, str), f"{name} must remain a literal reference miter")
            return value
    raise ValueError(f"Missing literal {name} miter in original runner")


def manifest_runtime_files() -> tuple[Path, dict[str, str], dict[str, object]]:
    manifest_path = LOCAL / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("schema") == "project-local-iverilog/1", "Pinned Icarus runtime manifest schema")
    require(manifest.get("versions", {}).get("iverilog", "").startswith("Icarus Verilog version 13.0"), "Pinned Icarus 13.0 runtime")
    files = manifest.get("files")
    require(isinstance(files, dict) and files, "Pinned Icarus runtime file manifest")
    paths: list[Path] = [manifest_path]
    expected: dict[str, str] = {}
    for relative, digest in files.items():
        path = LOCAL / Path(relative.replace("\\", "/"))
        require(path.is_file(), f"Pinned Icarus runtime file exists: {relative}")
        require(sha(path) == digest, f"Pinned Icarus runtime file hash: {relative}")
        paths.append(path)
        expected[source_key(path)] = digest
    expected[source_key(manifest_path)] = sha(manifest_path)
    return paths, expected, manifest


def check_report(report_path: Path, expected_status: str) -> dict[str, object]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    require(report.get("status") == expected_status, f"Expected prerequisite status: {report_path.name}")
    before = report.get("source_sha256_before")
    after = report.get("source_sha256_after")
    require(isinstance(before, dict) and before == after, f"Stable prerequisite source hashes: {report_path.name}")
    for name, expected in {**after, **report.get("artifact_sha256", {})}.items():
        path = resolve_source_key(name)
        require(path.is_file() and sha(path) == expected, f"Prerequisite source/artifact hash: {name}")
    return report


def build_miter(name: str, tb: Path, top: str, minimum: int,
                prepared: dict[str, object], build: Path) -> tuple[Path, Path]:
    original = tb.read_text(encoding="utf-8")
    require(original.count(top) == 1, f"Unique original {name} TB declaration")
    require(original.count("endmodule") == 1, f"Single original {name} TB module")
    require(original.count("$finish;") == 1, f"Single original {name} TB finish seam")
    body = literal_miter("PAIR" if name == "pair" else "ACCUM")
    generated = original.replace(top, top + "_fast_miter")
    generated = generated.replace("endmodule", body + "\nendmodule")
    generated = generated.replace(
        "$finish;",
        f'if(fast_checks<{minimum})$fatal(1,"Fast reference miter coverage");'
        f'$display("FAST_REFERENCE_MITER_PASS kind={name} checks=%0d",fast_checks);$finish;',
    )
    target = build / f"{top}_fast_miter.sv"
    target.write_text(generated, encoding="utf-8")

    old_artifacts = prepared.get("artifact_sha256", {})
    expected = next((digest for key, digest in old_artifacts.items()
                     if Path(key).name == target.name), None)
    require(expected is not None and sha(target) == expected, f"Exact prepared {name} miter source")

    # Icarus resolves declarations before procedural references; the prepared
    # Vivado miter placed fast_checks after the original TB's initial block.
    # Keep the prepared source above intact and compile a copy that only moves
    # this declaration to the module header. No expression or assertion changes.
    declaration = "integer fast_checks=0;"
    module_header = f"module {top}_fast_miter;\n"
    require(generated.count(declaration) == 1, f"Single {name} miter counter declaration")
    require(generated.count(module_header) == 1, f"Unique {name} generated module header")
    icarus_source = generated.replace(declaration, "", 1)
    icarus_source = icarus_source.replace(module_header, module_header + declaration + "\n", 1)
    normalized = icarus_source.replace(declaration + "\n", "", 1)
    prepared_without_decl = generated.replace(declaration, "", 1)
    require(normalized == prepared_without_decl, f"Only {name} counter declaration moved for Icarus")
    icarus_target = build / f"{top}_fast_miter_icarus.sv"
    icarus_target.write_text(icarus_source, encoding="utf-8")
    return target, icarus_target


def run_command(label: str, argv: list[Path | str], out: Path, build: Path,
                env: dict[str, str], commands: list[dict[str, object]], timeout: int) -> str:
    arguments = [str(item) for item in argv]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            arguments,
            cwd=build,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
        )
        log = proc.stdout + ("\n" if proc.stdout and proc.stderr else "") + proc.stderr
        (out / f"{label}.log").write_text(log, encoding="utf-8")
        commands.append({
            "name": label,
            "argv": arguments,
            "return_code": proc.returncode,
            "wall_seconds": round(time.monotonic() - started, 3),
        })
        require(proc.returncode == 0, f"{label} exited {proc.returncode}")
        require(ERROR_RE.search(log) is None, f"Strict {label} diagnostic scan")
        return log
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        log = stdout + ("\n" if stdout and stderr else "") + stderr
        (out / f"{label}.log").write_text(log, encoding="utf-8")
        commands.append({
            "name": label,
            "argv": arguments,
            "return_code": None,
            "wall_seconds": round(time.monotonic() - started, 3),
            "timeout_seconds": timeout,
        })
        raise ValueError(f"{label} timed out after {timeout}s") from exc


def marker_values(log: str, pattern: str, label: str) -> dict[str, int]:
    matches = re.findall(pattern, log, re.MULTILINE)
    require(len(matches) == 1, f"Exactly one {label} marker")
    return {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", matches[0])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    del args

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = ROOT / "validation/board_z100/native_primitive_refs_iverilog" / stamp
    build = ROOT / "build" / f"nprf_ivl_{stamp[-14:]}"
    out.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    report_path = out / "result.json"
    before: dict[str, str] = {}
    source_paths: list[Path] = []
    report: dict[str, object] = {
        "schema": "z100-native-primitive-refs-iverilog/1",
        "status": "RUNNING",
        "commands": [],
        "board_access": False,
        "simulation_references_only": True,
        "vendor_models_used": [str(DSP48E1), str(MULT_MACRO), str(GLBL)],
        "synthesis": False,
        "full_pipeline_30fps_accepted": False,
    }

    try:
        prepared = check_report(PREPARED, "PREPARED_SIMULATION_ONLY_PRIMITIVE_MITERS_NOT_EXECUTED")
        pair = check_report(PAIR_PROOF, "PASS_PRIVATE_EXACT_SIGNED_PAIR_HOST_XSIM_ONE_DSP_OOC_ONLY")
        accum = check_report(ACCUM_PROOF, "PASS_PRIVATE_SIGNED33_FEEDBACK_XSIM_ONE_DSP_OOC_ONLY")
        pair_sim = pair.get("simulation", {})
        accum_sim = accum.get("simulation", {})
        require(pair_sim.get("status") == "PASS" and pair_sim.get("inputs") == 1110260
                and pair_sim.get("output_pairs") == 1110258
                and pair_sim.get("consecutive_ii1") == 1048576,
                "Original full pair-suite coverage evidence")
        require(accum_sim.get("status") == "PASS" and accum_sim.get("checks") == 16754
                and accum_sim.get("loads") == 64 and accum_sim.get("updates") == 16528
                and accum_sim.get("flushes") == 17 and accum_sim.get("saturations") == 4087
                and accum_sim.get("consecutive_ii1") == 1024,
                "Original signed33 accumulator-suite coverage evidence")

        pair_module = ROOT / "deployment/hardware/z100_2026/int8_pair_packing_v3/z100_int8_pair_packing.sv"
        pair_tb = ROOT / "deployment/hardware/z100_2026/int8_pair_packing_v3/tb_z100_int8_pair_packing.sv"
        accum_module = ROOT / "deployment/hardware/z100_2026/accum33_dsp_v2/z100_accum33_dsp.sv"
        accum_tb = ROOT / "deployment/hardware/z100_2026/accum33_dsp_v2/tb_z100_accum33_dsp.sv"
        pair_prepared_miter, pair_miter = build_miter("pair", pair_tb, "tb_z100_int8_pair_packing", 1048576, prepared, build)
        accum_prepared_miter, accum_miter = build_miter("accum", accum_tb, "tb_z100_accum33_dsp", 16700, prepared, build)

        runtime_paths, runtime_hashes, manifest = manifest_runtime_files()
        binary = LOCAL / "ucrt64/bin"
        backend = LOCAL / "ucrt64/lib/ivl"
        iverilog = binary / "iverilog.exe"
        vvp = binary / "vvp.exe"
        required = [iverilog, vvp, backend, DSP48E1, MULT_MACRO, GLBL]
        require(all(path.exists() for path in required), "Pinned runtime backend and installed Vivado vendor sources")

        source_paths = [
            Path(__file__), PREPARED, PAIR_PROOF, ACCUM_PROOF, REFERENCE_RUNNER, REFERENCE,
            pair_module, pair_tb, accum_module, accum_tb, DSP48E1, MULT_MACRO, GLBL,
            *runtime_paths, pair_prepared_miter, accum_prepared_miter, pair_miter, accum_miter,
        ]
        before = sha_map(source_paths)
        require(all(before.get(name) == digest for name, digest in runtime_hashes.items()),
                "Pinned Icarus runtime hashes bound before execution")
        report.update(
            source_sha256_before=before,
            prepared_report=source_key(PREPARED),
            simulator=manifest.get("versions"),
            runtime_manifest_sha256=sha(LOCAL / "manifest.json"),
            runtime_manifest=source_key(LOCAL / "manifest.json"),
            vendor_sources=[source_key(DSP48E1), source_key(MULT_MACRO), source_key(GLBL)],
            miter_sha256={
                source_key(pair_prepared_miter): sha(pair_prepared_miter),
                source_key(accum_prepared_miter): sha(accum_prepared_miter),
                source_key(pair_miter): sha(pair_miter),
                source_key(accum_miter): sha(accum_miter),
            },
            scope=(
                "Executed the unchanged original signed INT8 pair and signed33 accumulator testbench bodies, "
                "with the exact previously prepared reference miter insertion and coverage marker. The "
                "Icarus compilation copy moves only the fast_checks integer declaration before procedural "
                "references; its assertions and logic are otherwise byte-identical to the prepared miter. "
                "Used the installed Vivado DSP48E1 and MULT_MACRO simulation sources plus vendor glbl. "
                "This establishes simulator-level arithmetic comparison only; no mapped-resource, timing, "
                "platform-integration, FPGA or physical-throughput claim."
            ),
        )
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

        env = dict(os.environ)
        env["PATH"] = str(binary) + os.pathsep + env.get("PATH", "")
        env["OMP_NUM_THREADS"] = "1"
        commands = report["commands"]
        version_log = run_command("iverilog_version", [iverilog, "-V"], out, build, env, commands, 30)
        vvp_version_log = run_command("vvp_version", [vvp, "-V"], out, build, env, commands, 30)
        require(manifest["versions"]["iverilog"] in version_log, "Icarus executable version matches runtime manifest")
        require("Icarus Verilog runtime version 13.0" in vvp_version_log, "VVP runtime version 13.0")

        pair_vvp = build / "pair_fast_miter.vvp"
        accum_vvp = build / "accum_fast_miter.vvp"
        pair_compile = [
            iverilog, "-B", backend, "-g2012", "-s", "tb_z100_int8_pair_packing_fast_miter", "-s", "glbl",
            "-o", pair_vvp, REFERENCE, MULT_MACRO, DSP48E1, GLBL, pair_module, pair_miter,
        ]
        accum_compile = [
            iverilog, "-B", backend, "-g2012", "-s", "tb_z100_accum33_dsp_fast_miter", "-s", "glbl",
            "-o", accum_vvp, REFERENCE, DSP48E1, GLBL, accum_module, accum_miter,
        ]
        run_command("pair_iverilog", pair_compile, out, build, env, commands, 120)
        run_command("accum_iverilog", accum_compile, out, build, env, commands, 120)
        pair_log = run_command("pair_vvp", [vvp, "-M", backend, pair_vvp], out, build, env, commands, 180)
        accum_log = run_command("accum_vvp", [vvp, "-M", backend, accum_vvp], out, build, env, commands, 60)

        pair_marker = marker_values(
            pair_log,
            r"^INT8_PAIR_PACKING_PASS (.+)$",
            "original pair suite",
        )
        require(pair_marker == {
            "inputs": 1110260, "outputs": 1110258, "ii1_streak": 1048576,
            "bubbles": 3870, "flushes": 2, "latency": 1,
        }, "Exact original pair-suite marker and coverage")
        pair_fast = re.findall(r"^FAST_REFERENCE_MITER_PASS kind=pair checks=(\d+)$", pair_log, re.MULTILINE)
        require(len(pair_fast) == 1 and int(pair_fast[0]) == pair_marker["outputs"],
                "Exact pair reference-miter marker and all output checks")
        require(len(re.findall(r"\$finish called at", pair_log)) == 1, "Pair simulation reached exactly one original finish")

        accum_marker = marker_values(
            accum_log,
            r"^ACCUM33_DSP_PASS (.+)$",
            "original accumulator suite",
        )
        require(accum_marker == {
            "checks": 16754, "loads": 64, "updates": 16528, "holds": 145,
            "flushes": 17, "saturations": 4087, "ii1_streak": 1024,
        }, "Exact original accumulator-suite marker and coverage")
        accum_fast = re.findall(r"^FAST_REFERENCE_MITER_PASS kind=accum checks=(\d+)$", accum_log, re.MULTILINE)
        require(len(accum_fast) == 1 and int(accum_fast[0]) >= 16700,
                "Accumulator reference-miter coverage marker")
        require(len(re.findall(r"\$finish called at", accum_log)) == 1, "Accumulator simulation reached exactly one original finish")

        report.update(
            status="PASS_ICARUS_ACTUAL_VENDOR_DSP48E1_AND_MULT_MACRO_REFERENCE_MITERS_SIMULATION_ONLY",
            miters=[
                {"kind": "pair", "checks": int(pair_fast[0]), "original_suite": pair_marker},
                {"kind": "accum", "checks": int(accum_fast[0]), "original_suite": accum_marker},
            ],
            diagnostics={
                "pair_compile_warnings": len(re.findall(r"\bwarning:", (out / "pair_iverilog.log").read_text(encoding="utf-8"), re.IGNORECASE)),
                "accum_compile_warnings": len(re.findall(r"\bwarning:", (out / "accum_iverilog.log").read_text(encoding="utf-8"), re.IGNORECASE)),
            },
        )
    except Exception as exc:
        report.update(status="FAILED_CLOSED", error=f"{type(exc).__name__}: {exc}")

    try:
        if source_paths:
            after = sha_map(source_paths)
            report["source_sha256_before"] = before
            report["source_sha256_after"] = after
            if before != after:
                report["status"] = "FAILED_SOURCE_INTEGRITY"
                report["error"] = "Bound source, vendor or runtime file changed during validation"
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
