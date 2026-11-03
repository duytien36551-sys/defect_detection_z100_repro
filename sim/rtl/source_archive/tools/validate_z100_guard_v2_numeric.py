#!/usr/bin/env python3
"""Run the frozen MMIO first-event numerical golden against the guard-v2 backend.

The runner keeps the original numeric testbench and golden fixtures intact. It
creates a build-local testbench copy that changes only the selected wrapper
module name, and compiles the source-bound guard-v2 closure with Icarus. By
default it only stages the run. Numerical execution is blocked while Vivado is
active so it cannot compete with the unique in-progress route.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_MANIFEST = ROOT / "deployment/build/z100_native_conv_backend_v3_review/20261026T063511.355431Z/source_manifest.json"
GUARD_MANIFEST = ROOT / "deployment/hardware/z100_2026/native_conv_backend_v3_resident_guard_v2/source_manifest_guard_v2.json"
GUARD_RESULT = ROOT / "validation/board_z100/native_conv_backend_v3_resident_guard_v2/20261027T000654.978160Z/result.json"
FIXTURE_RESULT = ROOT / "validation/board_z100/native_conv_first_event_v2/20261026T064115.441661Z/result.json"
MMIO_TB = ROOT / "deployment/simulation/native_conv_mmio_first_event_v1/tb_z100_native_conv_mmio_first_event_v1.sv"
OLD_MMIO_WRAPPER = ROOT / "deployment/hardware/z100_2026/native_conv_mmio_backend_v1/z100_native_conv_mmio_backend_v1.sv"
GUARD_DIR = ROOT / "deployment/hardware/z100_2026/native_conv_backend_v3_resident_guard_v2"
GUARD_BACKEND = GUARD_DIR / "z100_native_conv_backend_v3_resident_guard_v2.sv"
GUARD_MMIO = GUARD_DIR / "z100_native_conv_mmio_backend_resident_guard_v2.sv"
GUARD_HELPER = GUARD_DIR / "z100_parameter_residency_guard_v2.sv"
FRONTEND = ROOT / "deployment/hardware/z100_2026/native_conv_mmio_v2/z100_native_conv_mmio_v2.sv"
FIXTURE_BUILD = ROOT / "deployment/build/native_conv_first_event_v2/20261026T064115.441661Z"
LOCAL = ROOT / "deployment/build/local_tools/iverilog13_msys2/ucrt64"
VENDOR = Path("C:/appload/2026.1/Vivado/data/verilog/src")
BUILD_ROOT = ROOT / "deployment/build/guard_v2_numeric"
EVIDENCE_ROOT = ROOT / "validation/board_z100/guard_v2_numeric"

FIXTURE_ASSETS = (
    "conv_event_map.hex", "conv_tiles.hex", "directory.hex", "parameter_memory.hex",
    "input_native_DDR.hex", "expected_raw_words.hex", "expected_post_words.hex",
    "expected_packed_words.hex", "expected_native_DDR.hex",
)
FIXTURE_HASHES = {
    "conv_event_map.hex": "7f5dbedbc8b0487350ea40465b2e6ae1bc404e6c167da25b72cedf94e4dbaf85",
    "conv_tiles.hex": "8295ab50a944c6b8c61b97515d8a388919f287dd2c487c63c6da997a64c99f0c",
    "directory.hex": "41dab50f4db049ee3072cf41a7cd5927368f6f7a2b2608c1396c93b6d020ac93",
    "parameter_memory.hex": "d820670a3577e08b2cce29522f6500ae59dc32298e0eae30a7685090530d1cc2",
    "input_native_DDR.hex": "4a40ee9516e069766aa1974d02a6eef09cccafa4a7e83923b5d2653f728055ce",
    "expected_raw_words.hex": "624f4417828a755b2bc71a2d63d6afc172e9a2e13abea70c799c068ad3128c56",
    "expected_post_words.hex": "48cd3d7f3cafe8d4469c14d1ecbc2af830cd747c2d0f531ec6a6ce2f267f2271",
    "expected_packed_words.hex": "06d3cf5cd1aeae8d6da0986bb2bbd83489ab89f77f1c3948a62b28793a7fa3bb",
    "expected_native_DDR.hex": "c75f14182d94f6da45829c51213000f78e1d9a2a3de90784a42ea6840c80c662",
}
VENDOR_HASHES = {
    "DSP48E1.v": "4060111c8de44f786fdc982de9caaa88fc0b2c44fcd6d0f0f7ec188a58793bd0",
    "MULT_MACRO.v": "d8ad46e2f5c808f52d4029025695ff7f67d6526c009bcaba0a75e84eecc27a2c",
    "glbl.v": "6270251cf35e1fce3119fc79f8fb968912f7983027e43cf030409ba68f048936",
}
BASE_BACKEND_SUFFIX = "native_conv_backend_v3/z100_native_conv_backend_v3.sv"
TOP = "tb_z100_native_conv_mmio_first_event_v1"
GUARD_MMIO_TOP = "z100_native_conv_mmio_backend_resident_guard_v2"
PASS_PREFIX = "MMIO_FIRST_EVENT_PASS "


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def module_ports(text: str, module: str) -> list[str]:
    match = re.search(rf"module\s+{re.escape(module)}\s*#\s*\(.*?\)\s*\((.*?)\)\s*;", text, re.S)
    require(match is not None, f"Could not read module port list: {module}")
    return re.findall(r"\b(?:input|output|inout)\s+(?:(?:wire|reg|logic)\s+)?(?:\[[^\]]+\]\s*)?(\w+)", match.group(1))


def process_ids(name: str) -> list[dict[str, Any]]:
    script = f"Get-CimInstance Win32_Process -Filter \"Name='{name}'\" | Select-Object ProcessId,Name,CreationDate,CommandLine | ConvertTo-Json -Compress"
    completed = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                               text=True, capture_output=True, check=True)
    payload = completed.stdout.strip()
    if not payload:
        return []
    parsed = json.loads(payload)
    return parsed if isinstance(parsed, list) else [parsed]


def build_source_closure() -> tuple[list[Path], dict[str, str], dict[str, Any]]:
    base = read_json(BASE_MANIFEST)
    guard = read_json(GUARD_MANIFEST)
    guard_result = read_json(GUARD_RESULT)
    fixture = read_json(FIXTURE_RESULT)
    require(base.get("status") == "LOCAL_ELABORATION_REVIEWED_NOT_FUNCTIONAL_OR_SYNTHESIS",
            "Pinned base V3 source manifest status changed")
    require(guard.get("status") == "LOCAL_PROTOCOL_AND_ELABORATION_ONLY",
            "Guard-v2 source manifest status changed")
    require(guard_result.get("status") == "PASS_HELPER_PROTOCOL_AND_MMIO_ELABORATION_ONLY",
            "Guard-v2 protocol/elaboration prerequisite is not the pinned pass")
    require(fixture.get("status") == "PREPARED_LOCAL_ELABORATION_PASS_NUMERICAL_UNEXECUTED" and
            fixture.get("numerical_simulation_run") is False,
            "Pinned first-event golden fixture has unexpected status")
    require(len(base.get("synthesis_sources", {})) == 35, "Expected the reviewed 35-file V3 closure")
    require(guard.get("base_v3_rtl_count") == 35 and guard.get("tops", {}).get("mmio") == GUARD_MMIO_TOP,
            "Guard manifest top or source count changed")

    sources: list[Path] = []
    pins: dict[str, str] = {}
    replaced = 0
    for rel, digest in base["synthesis_sources"].items():
        normalized = rel.replace("\\", "/")
        path = ROOT / normalized
        require(path.is_file() and sha256(path) == digest, f"Base V3 source identity mismatch: {normalized}")
        if normalized.endswith(BASE_BACKEND_SUFFIX):
            path = GUARD_BACKEND
            replaced += 1
            expected = guard["sources"][relative(path)]
            require(path.is_file() and sha256(path) == expected, "Guard backend hash differs from its manifest")
            pins[relative(path)] = expected
        else:
            pins[normalized] = digest
        sources.append(path.resolve())
    require(replaced == 1, "Expected one base Conv backend replacement")

    for path in (FRONTEND, GUARD_MMIO, GUARD_HELPER):
        rel = relative(path)
        expected = guard["sources"].get(rel)
        require(expected is not None and path.is_file() and sha256(path) == expected,
                f"Guard-v2 source identity mismatch: {rel}")
        sources.append(path.resolve())
        pins[rel] = expected
    require(len(sources) == 38 and len(set(sources)) == 38, "Guard-v2 simulation source closure count/uniqueness")

    old_text = OLD_MMIO_WRAPPER.read_text(encoding="utf-8")
    guarded_text = GUARD_MMIO.read_text(encoding="utf-8")
    old_ports = module_ports(old_text, "z100_native_conv_mmio_backend_v1")
    guard_ports = module_ports(guarded_text, GUARD_MMIO_TOP)
    require(old_ports == guard_ports, "Guarded MMIO wrapper ports differ from the frozen MMIO fixture")
    require(len(old_ports) == len(set(old_ports)), "MMIO wrapper port list has duplicates")
    pins[relative(FRONTEND)] = guard["sources"][relative(FRONTEND)]
    pins[relative(OLD_MMIO_WRAPPER)] = sha256(OLD_MMIO_WRAPPER)
    pins[relative(GUARD_MANIFEST)] = sha256(GUARD_MANIFEST)
    pins[relative(BASE_MANIFEST)] = sha256(BASE_MANIFEST)
    pins[relative(GUARD_RESULT)] = sha256(GUARD_RESULT)
    pins[relative(FIXTURE_RESULT)] = sha256(FIXTURE_RESULT)
    pins[relative(MMIO_TB)] = sha256(MMIO_TB)
    return sources, pins, {"fixture": fixture, "guard_manifest": guard, "wrapper_ports": len(old_ports)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-icarus", action="store_true", help="Compile and run the full frozen MMIO first-event golden")
    parser.add_argument("--simulation-timeout-seconds", type=int, default=3600)
    args = parser.parse_args()
    require(60 <= args.simulation_timeout_seconds <= 7200, "Simulation timeout must be 60..7200 seconds")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    build = BUILD_ROOT / stamp
    evidence = EVIDENCE_ROOT / stamp
    build.mkdir(parents=True, exist_ok=False)
    evidence.mkdir(parents=True, exist_ok=False)
    report_path = evidence / "result.json"
    report: dict[str, Any] = {
        "schema": "z100-native-guard-v2-numeric/1",
        "status": "PREFLIGHT",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "board_access": False,
        "vivado_run": False,
        "numerical_simulation_run": False,
        "full_conv_event_accepted": False,
        "fullgraph_accepted": False,
        "physical_30fps_accepted": False,
        "scope": "Frozen 640x640 first Conv event through the guard-v2 integrated MMIO backend; independent original OIHW/native-DDR goldens. This is not full graph execution, synthesis, routing, board inference, or FPS evidence.",
        "build_dir": relative(build),
        "evidence_dir": relative(evidence),
    }

    def save() -> None:
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    try:
        sources, pins, context = build_source_closure()
        require(sha256(MMIO_TB) == pins[relative(MMIO_TB)], "Frozen numerical testbench changed during preflight")
        fixture = context["fixture"]
        staged: dict[str, str] = {}
        for name in FIXTURE_ASSETS:
            src = FIXTURE_BUILD / name
            expected = FIXTURE_HASHES[name]
            require(src.is_file() and sha256(src) == expected and fixture["artifact_sha256"].get(
                (Path(fixture["build_dir"]) / name).as_posix()) == expected,
                f"Original golden fixture identity mismatch: {name}")
            dst = build / name
            dst.write_bytes(src.read_bytes())
            require(sha256(dst) == expected, f"Staged original fixture changed: {name}")
            staged[name] = expected
            pins[relative(src)] = expected
            pins[relative(dst)] = expected

        original_tb = MMIO_TB.read_text(encoding="utf-8")
        old_instance = "z100_native_conv_mmio_backend_v1 #("
        require(original_tb.count(old_instance) == 1, "Expected the unique frozen MMIO DUT instance")
        generated_tb_text = original_tb.replace(old_instance, GUARD_MMIO_TOP + " #(", 1)
        require(generated_tb_text.count("z100_native_conv_mmio_backend_v1 #(") == 0 and
                generated_tb_text.count(GUARD_MMIO_TOP + " #(") == 1,
                "Generated TB does not select exactly the guard-v2 MMIO wrapper")
        generated_tb = build / "tb_z100_native_conv_mmio_first_event_guard_v2.sv"
        generated_tb.write_text(generated_tb_text, encoding="utf-8")

        vendor = [VENDOR / "unisims/DSP48E1.v", VENDOR / "unimacro/MULT_MACRO.v", VENDOR / "glbl.v"]
        for path in vendor:
            expected = VENDOR_HASHES[path.name]
            require(path.is_file() and sha256(path) == expected, f"Vivado simulation model identity mismatch: {path.name}")
            pins["external/" + path.as_posix()] = expected
        compiler = LOCAL / "bin/iverilog.exe"
        simulator = LOCAL / "bin/vvp.exe"
        require(compiler.is_file() and simulator.is_file(), "Pinned local Icarus tools are unavailable")
        for path in (compiler, simulator):
            pins[relative(path)] = sha256(path)
        pins[relative(GUARD_BACKEND)] = sha256(GUARD_BACKEND)
        pins[relative(GUARD_MMIO)] = sha256(GUARD_MMIO)
        pins[relative(GUARD_HELPER)] = sha256(GUARD_HELPER)
        pins[relative(generated_tb)] = sha256(generated_tb)
        pins[relative(Path(__file__))] = sha256(Path(__file__))

        image = build / "guard_v2_numeric.vvp"
        compile_argv = [str(compiler), "-B", str(LOCAL / "lib/ivl"), "-g2012", "-Wall",
                        "-s", TOP, "-s", "glbl", "-o", str(image),
                        *map(str, sources), *map(str, vendor), str(generated_tb)]
        run_argv = [str(simulator), "-M", str(LOCAL / "lib/ivl"), str(image)]
        (build / "commands.json").write_text(json.dumps({"cwd": str(build), "compile": compile_argv,
            "simulate": run_argv, "simulation_timeout_seconds": args.simulation_timeout_seconds}, indent=2) + "\n",
            encoding="utf-8")
        report.update(status="PREPARED_GUARD_V2_REAL_GOLDEN_NOT_EXECUTED",
                      selected_wrapper=GUARD_MMIO_TOP, selected_backend="z100_native_conv_backend_v3_resident_guard_v2",
                      source_count=len(sources), source_files=[relative(p) for p in sources],
                      frozen_testbench=relative(MMIO_TB), generated_testbench_sha256=sha256(generated_tb),
                      generated_testbench_change="single module token at DUT instantiation selects the guard-v2 MMIO wrapper",
                      original_fixture_sha256=staged, wrapper_port_count=context["wrapper_ports"],
                      source_sha256_before=pins, commands={"compile": compile_argv, "simulate": run_argv},
                      numeric_coverage_expected={"tiles": 16, "raw_records": 102400, "post_records": 102400,
                          "packed_words": 25600, "source_R_beats": 209600, "parameter_R_beats": 3712,
                          "output_W_beats": 204800, "output_AW_B_bursts": 12800, "guard_words": 57344},
                      pass_marker_expected="MMIO_FIRST_EVENT_PASS")
        report["source_sha256_after"] = {
            key: (sha256(Path(key.removeprefix("external/"))) if key.startswith("external/")
                  else sha256(ROOT / key)) for key in pins
        }
        require(report["source_sha256_before"] == report["source_sha256_after"],
                "Pinned input source changed during preparation")
        report["artifact_sha256"] = {
            relative(path): sha256(path) for folder in (build, evidence) for path in folder.rglob("*")
            if path.is_file() and path != report_path
        }
        save()

        if not args.run_icarus:
            print(json.dumps({"status": report["status"], "report": relative(report_path)}, indent=2))
            return 0

        running_vivado = process_ids("vivado.exe")
        report["vivado_processes_at_execution_gate"] = running_vivado
        if running_vivado:
            report.update(status="BLOCKED_ROUTE_PROCESS_ACTIVE",
                          error="Icarus full-event execution held while Vivado routing is active; rerun after it exits.")
            report["source_sha256_after"] = {}
            for key in pins:
                path = Path(key.removeprefix("external/")) if key.startswith("external/") else ROOT / key
                report["source_sha256_after"][key] = sha256(path) if path.is_file() else None
            report["artifact_sha256"] = {
                relative(path): sha256(path) for folder in (build, evidence) for path in folder.rglob("*")
                if path.is_file() and path != report_path
            }
            save()
            print(json.dumps({"status": report["status"], "report": relative(report_path)}, indent=2))
            return 2

        # Verify all inputs again immediately before starting the potentially long simulation.
        for key, expected in pins.items():
            if key.startswith("external/"):
                path = Path(key.removeprefix("external/"))
            else:
                path = ROOT / key
            require(path.is_file() and sha256(path) == expected, f"Source drift before execution: {key}")

        for label, argv, timeout in (("compile", compile_argv, 600),
                                     ("simulate", run_argv, args.simulation_timeout_seconds)):
            if label == "simulate":
                report["status"] = "RUNNING_GUARD_V2_NUMERICAL_SIMULATION"
                save()
            log_path = evidence / (label + ".log")
            started = time.monotonic()
            try:
                completed = subprocess.run(argv, cwd=build, text=True, errors="replace",
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False,
                    env=dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1"))
            except subprocess.TimeoutExpired as exc:
                output = exc.stdout or ""
                if isinstance(output, bytes):
                    output = output.decode(errors="replace")
                log_path.write_text(output, encoding="utf-8")
                report.update(status="FAILED_TIMEOUT_" + label.upper(), error=f"{label} exceeded {timeout}s")
                save()
                return 1
            elapsed = time.monotonic() - started
            log_path.write_text(completed.stdout, encoding="utf-8")
            report.setdefault("steps", []).append({"step": label, "return_code": completed.returncode,
                "elapsed_seconds": round(elapsed, 3), "log": relative(log_path), "argv": argv})
            save()
            require(completed.returncode == 0, f"Icarus {label} returned {completed.returncode}")
            require(not re.search(r"(?:^|\n)\s*(?:error:|fatal:|ERROR:)", completed.stdout, re.I),
                    f"Icarus {label} emitted an error/fatal diagnostic")

        simulation_text = (evidence / "simulate.log").read_text(encoding="utf-8", errors="replace")
        markers = re.findall(r"^MMIO_FIRST_EVENT_PASS .+$", simulation_text, re.M)
        require(len(markers) == 1, "Expected exactly one full-event numeric marker")
        marker = markers[0]
        counts = {key: int(value) for key, value in re.findall(r"([A-Za-z_]+)=(\d+)", marker)}
        required_counts = {"tiles": 16, "raw": 102400, "post": 102400, "packed": 25600,
            "source_R": 209600, "parameter_R": 3712, "output_W": 204800,
            "output_AW_B": 12800, "guards": 57344, "mmio_shadow": 27,
            "mmio_start": 1, "mmio_ack": 1, "mmio_results": 10}
        require(all(counts.get(key) == value for key, value in required_counts.items()),
                "Full-event count coverage does not match frozen fixture")
        require("producer_complete=PHYSICAL_TILES_ONLY ledger_publication=NOT_CLAIMED" in marker,
                "Marker unexpectedly claims full tensor publication")
        report.update(status="PASS_GUARD_V2_FULL_FIRST_CONV_GOLDEN_NOT_FULLGRAPH",
                      numerical_simulation_run=True, full_conv_event_accepted=True,
                      simulation_counts=counts, marker=marker)
    except Exception as exc:
        report.update(status="FAILED_CLOSED", error=f"{type(exc).__name__}: {exc}")

    report["source_sha256_after"] = {}
    for key in report.get("source_sha256_before", {}):
        if key.startswith("external/"):
            path = Path(key.removeprefix("external/"))
        else:
            path = ROOT / key
        report["source_sha256_after"][key] = sha256(path) if path.is_file() else None
    if report.get("source_sha256_before") != report["source_sha256_after"]:
        report.update(status="FAILED_SOURCE_INTEGRITY", error="Pinned source hash changed")
    report["artifact_sha256"] = {
        relative(path): sha256(path) for folder in (build, evidence) for path in folder.rglob("*")
        if path.is_file() and path != report_path
    }
    save()
    print(json.dumps({"status": report["status"], "report": relative(report_path),
                      "error": report.get("error")}, indent=2))
    return 0 if report["status"].startswith("PASS_") or report["status"].startswith("PREPARED_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
