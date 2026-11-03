"""Integrate the staged 20-site output packer into the frozen V12 core.

This runner keeps the candidate isolated. It first runs the accepted V12
original-golden numerical testbench with only a timing-aware staged-copy
adaptation, then runs the separately supplied full-top control testbench, and
only then starts a fresh 10 ns full-core Vivado implementation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import ctypes
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import validate_z100_feature_input_capture_v12 as v12  # noqa: E402
import route_z100_feature_input_capture_v12 as v12route  # noqa: E402
import review_z100_v10_route_recovery_v1 as route_review  # noqa: E402


OUT_ROOT = ROOT / "validation/board_z100/staged_packer_core_v1"
BUILD_ROOT = ROOT / "build"
MANIFEST_PATH = ROOT / "deployment/hardware/z100_2026/native_output_packer_staged_v3/integration_candidate.json"
PACKER_PATH = ROOT / "deployment/hardware/z100_2026/native_output_packer_staged_v3/z100_native_output_packer.sv"
CONTROL_TB_PATH = ROOT / "deployment/hardware/z100_2026/native_output_packer_staged_v3/tb_z100_staged_packer_core_control.sv"
FROZEN_RTL = ROOT / "build/v12p_d46da432/rtl"
VENDOR = v12.VENDOR
VIVADO = VENDOR / "vivado.bat"
PART = "xc7z100ffg900-2"
TOP = v12.NEW_TOP_NAME
PERIOD_NS = 10.0
SYNTH_THREADS = 2
IMPLEMENTATION_THREADS = 8
EXPECTED_PACKER_SHA256 = "3be946a4020dddbabbf179d1921990f4f884e2826c7e3c9575730edb3f979a87"
EXPECTED_FROZEN_PACKER_SHA256 = "f13d0686e94480e78f967ebb5242ef5686728440bd527b640c26541d54c25c31"
EXPECTED_V10_PROOF = "validation/board_z100/feature_address_shared_v10_compute/20261025T190545.372805Z/result.json"
EXPECTED_V10_PROOF_SHA256 = "489c5edc846a30445e6ae1d108ec628afd32712c8b618685a8f1b2112cd46daa"
EXPECTED_PACKAGE_SHA256 = "65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c"
EXPECTED_PACKAGE_PATH = "deployment/candidates/pin640/quant_candidates/epoch200_head_concat_20261024T103836.103919Z/package/MODEL.V8P"
EXPECTED_MODEL_ID_REPORT = "validation/board_z100/accelerator_stage_acceptance/20261026T205527.098826Z_d6d4cb/result.json"
EXPECTED_MODEL_ID = {"domain": "pin", "epoch": 200, "input": "640x640", "classes": 9,
                     "protocol": "pin9-v8/2-input640", "package_sha256": EXPECTED_PACKAGE_SHA256}
TIMING_COUNTER_WHITELIST = {
    "packed_stall", "pool_stalls", "overlap_cycles", "simultaneous_window_load", "contended_cycles",
}
NUMERIC_TB_REWRITE_FROM = (
    '            @(posedge clk); #1;\n'
    '            if (!pack_active || pack_error_valid) $fatal(1, "packer config failed");\n'
    '            @(negedge clk); pack_cfg_valid = 0;'
)
NUMERIC_TB_REWRITE_TO = (
    '            @(posedge clk); #1;\n'
    '            if (pack_active || pack_error_valid)\n'
    '                $fatal(1, "packer committed before E4 after E0");\n'
    '            @(negedge clk); pack_cfg_valid = 0;\n'
    '            repeat (3) begin\n'
    '                @(posedge clk); #1;\n'
    '                if (pack_active || pack_error_valid)\n'
    '                    $fatal(1, "packer committed before E4");\n'
    '            end\n'
    '            @(posedge clk); #1;\n'
    '            if (!pack_active || pack_error_valid) $fatal(1, "packer config failed at E4");\n'
    '            @(negedge clk);'
)


class RunError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RunError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunError(f"cannot read JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")


def tcl_path(path: Path) -> str:
    return "{" + Path(path).resolve().as_posix() + "}"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def bind(inputs: dict[str, str], path: Path, expected: str | None = None) -> str:
    path = Path(path).resolve(strict=True)
    digest = sha256_file(path)
    require(expected is None or digest == expected, f"source hash mismatch: {v12.project_name(path)}")
    name = v12.project_name(path)
    require(name not in inputs or inputs[name] == digest, f"conflicting source binding: {name}")
    inputs[name] = digest
    return digest


def copy_verified(source: Path, target: Path, artifacts: dict[str, str]) -> Path:
    source = Path(source).resolve(strict=True)
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    digest = sha256_file(source)
    require(sha256_file(target) == digest, f"stage copy mismatch: {source}")
    artifacts[v12.project_name(target)] = digest
    return target


def artifact_hashes(out: Path, build: Path, report: Path) -> dict[str, str]:
    files = [path for folder in (out, build) for path in folder.rglob("*")
             if path.is_file() and path.resolve() != report.resolve()]
    return {v12.project_name(path): sha256_file(path) for path in sorted(files)}


def refresh_source_after(result: dict[str, Any]) -> None:
    before = result.get("source_sha256_before", {})
    result["source_sha256_after"] = {
        name: sha256_file(v12.resolve(name)) for name in sorted(before)
    }
    result["source_integrity_passed"] = result["source_sha256_after"] == before


def persist(result: dict[str, Any]) -> None:
    result["last_heartbeat_utc"] = now_utc()
    path = v12.resolve(result["report"])
    save_json(path, result)


def update_artifacts(result: dict[str, Any]) -> None:
    out = v12.resolve(result["run_directory"])
    build = v12.resolve(result["build_directory"])
    report = v12.resolve(result["report"])
    result["artifact_sha256"] = artifact_hashes(out, build, report)


def parse_marker(line: str) -> tuple[str, dict[str, int]]:
    parts = line.strip().split()
    require(parts, f"empty simulation marker: {line!r}")
    values: dict[str, int] = {}
    for key, value in re.findall(r"(\w+)=(-?\d+)", line):
        require(key not in values, f"duplicate marker field {key}: {line}")
        values[key] = int(value)
    return parts[0], values


def marker_lines(text: str, suffix: str = "_PASS") -> list[str]:
    return [line.strip() for line in text.splitlines()
            if line.strip() and line.strip().split()[0].endswith(suffix)]


def compare_numeric_markers(baseline: list[str], actual: list[str]) -> dict[str, Any]:
    require(len(baseline) == 7 and len(actual) == 7, "original-golden run must emit exactly seven PASS markers")
    differences: dict[str, dict[str, int]] = {}
    exact_fields = 0
    for marker_index, (before, after) in enumerate(zip(baseline, actual)):
        base_name, base_values = parse_marker(before)
        actual_name, actual_values = parse_marker(after)
        require(base_name == actual_name,
                f"original-golden marker order/name mismatch at {marker_index}: {base_name} != {actual_name}")
        require(set(base_values) == set(actual_values), f"marker field set changed: {base_name}")
        for key in sorted(base_values):
            if base_values[key] == actual_values[key]:
                exact_fields += 1
                continue
            require(key in TIMING_COUNTER_WHITELIST,
                    f"non-timing original-golden field changed: {base_name}.{key} "
                    f"{base_values[key]} -> {actual_values[key]}")
            differences[f"{base_name}.{key}"] = {
                "baseline": base_values[key], "candidate": actual_values[key],
                "delta": actual_values[key] - base_values[key],
            }
    return {
        "baseline_markers": baseline,
        "candidate_markers": actual,
        "timing_counter_whitelist": sorted(TIMING_COUNTER_WHITELIST),
        "timing_counter_differences": differences,
        "all_other_fields_exact": True,
        "exact_field_count": exact_fields,
    }


class VendorMutex:
    def __init__(self) -> None:
        require(os.name == "nt", "shared Vivado mutex requires Windows")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        self.kernel.CreateMutexW.restype = ctypes.c_void_p
        self.kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.kernel.WaitForSingleObject.restype = ctypes.c_ulong
        self.kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handle: int | None = None
        self.owned = False

    def acquire(self) -> dict[str, Any]:
        require(self.handle is None, "mutex object already initialized")
        self.handle = self.kernel.CreateMutexW(None, False, "Local\\Z100_Vivado_Implementation")
        require(bool(self.handle), f"CreateMutexW failed: {ctypes.get_last_error()}")
        result = int(self.kernel.WaitForSingleObject(self.handle, 0))
        require(result in (0, 0x80), "shared Vivado implementation mutex is already held")
        self.owned = True
        return {"name": "Local\\Z100_Vivado_Implementation", "wait_result": hex(result),
                "abandoned_owner_recovered": result == 0x80}

    def release(self) -> None:
        if self.handle is not None:
            if self.owned:
                self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            self.owned = False


def assert_vendor_idle(result: dict[str, Any]) -> list[dict[str, Any]]:
    inventory = v12.process_inventory()
    active = [row for row in inventory if str(row.get("Name", "")).lower() in v12.VENDOR_NAMES]
    require(not active, f"vendor process inventory is not idle before launch: {active}")
    result.setdefault("process_checks", []).append({"at_utc": now_utc(), "active_vendor_processes": active,
                                                     "status": "PASS_IDLE"})
    return inventory


def run_vendor_command(result: dict[str, Any], label: str, argv: list[Any], cwd: Path,
                       log_path: Path, heartbeat_seconds: int = 10) -> str:
    assert_vendor_idle(result)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, XILINX_LOCAL_USER_DATA="no", OMP_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    entry: dict[str, Any] = {
        "label": label, "argv": list(map(str, argv)), "cwd": v12.project_name(cwd),
        "log": v12.project_name(log_path), "started_at_utc": now_utc(), "status": "RUNNING",
    }
    result.setdefault("commands", []).append(entry)
    result["phase"] = label
    persist(result)
    started = time.monotonic()
    try:
        with log_path.open("w", encoding="utf-8", newline="\n") as stream:
            proc = subprocess.Popen(list(map(str, argv)), cwd=cwd, env=env,
                                    stdout=stream, stderr=subprocess.STDOUT)
            entry["pid"] = proc.pid
            entry["process_identity"] = [{"pid": proc.pid, "kind": "launcher"}]
            persist(result)
            next_heartbeat = time.monotonic() + heartbeat_seconds
            while proc.poll() is None:
                time.sleep(2)
                if time.monotonic() >= next_heartbeat:
                    try:
                        rows = v12.process_inventory()
                        entry["process_identity"] = [
                            {"pid": row.get("ProcessId"), "name": row.get("Name"),
                             "command_line": row.get("CommandLine")}
                            for row in rows if str(row.get("Name", "")).lower() in v12.VENDOR_NAMES
                        ]
                    except Exception as exc:
                        entry["process_inventory_error"] = f"{type(exc).__name__}: {exc}"
                    result["last_heartbeat_utc"] = now_utc()
                    persist(result)
                    next_heartbeat = time.monotonic() + heartbeat_seconds
            return_code = int(proc.returncode)
    except OSError as exc:
        entry.update(status="FAILED_LAUNCH", error=f"{type(exc).__name__}: {exc}")
        persist(result)
        raise RunError(f"cannot launch {label}: {exc}") from exc

    entry.update(return_code=return_code, wall_seconds=time.monotonic() - started,
                 finished_at_utc=now_utc(), log_sha256=sha256_file(log_path),
                 status="PASS" if return_code == 0 else "FAILED")
    text = log_path.read_text(encoding="utf-8", errors="replace")
    result["phase"] = label + ("_COMPLETE" if return_code == 0 else "_FAILED")
    persist(result)
    require(return_code == 0, f"{label} returned {return_code}; see {log_path}")
    require(not re.search(r"^\s*(?:ERROR:|Fatal:|FATAL:)", text, re.MULTILINE),
            f"{label} emitted a fatal diagnostic; see {log_path}")
    assert_vendor_idle(result)
    return text


def make_run_dirs() -> tuple[str, Path, Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_id = stamp + "_" + secrets.token_hex(3)
    output = OUT_ROOT / run_id
    build = BUILD_ROOT / ("spc_" + stamp.replace(".", "") + "_" + secrets.token_hex(3))
    output.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    return run_id, output, build, output / "result.json"


def prepare_run() -> tuple[dict[str, Any], Path]:
    run_id, output, build, report = make_run_dirs()
    result: dict[str, Any] = {
        "schema": "z100-staged-packer-full-core-integration/1",
        "run_id": run_id,
        "status": "PREPARING_SOURCE_BOUND_RUN",
        "created_at_utc": now_utc(),
        "report": v12.project_name(report),
        "run_directory": v12.project_name(output),
        "build_directory": v12.project_name(build),
        "scope": "Frozen28-file V12 native20-site core with exactly one staged output-packer override; no board access, platform integration, full graph accuracy, or FPS acceptance.",
        "board_access": False,
        "platform_integrated": False,
        "fullgraph_execution_accepted": False,
        "physical_30fps_accepted": False,
        "synthesis_or_route_accepted": False,
        "part": PART,
        "top": TOP,
        "clock_period_ns": PERIOD_NS,
        "clock_constraints": "Only create_clock -name row_clk -period 10 [get_ports clk], matching clock-only A comparison; no I/O delays, Pblock, or inherited DCP.",
        "fresh_synthesis": True,
        "synthesis_max_threads": SYNTH_THREADS,
        "implementation_max_threads": IMPLEMENTATION_THREADS,
        "route_directive": "Default",
        "pre_route_phys_opt": "phys_opt_design -hold_fix",
        "post_route_physical_optimization": False,
        "source_sha256_before": {},
        "source_sha256_after": {},
        "staged_artifacts": {},
        "artifact_sha256": {},
        "commands": [],
        "checks": [],
        "errors": [],
        "run_steps": {},
        "process_checks": [],
        "old_physical_lock_observation": {
            "path": "validation/board_z100/feature_input_capture_v12/physical/.vivado.lock",
            "status": "STALE_PID_ABSENT_PRESERVED",
            "note": "Prior run PID 36460 was absent at launch; its RUNNING report and pre-route checkpoints were left untouched. Shared named mutex and actual process inventory gate this run.",
        },
    }
    inputs: dict[str, str] = {}
    artifacts: dict[str, str] = {}
    report.parent.mkdir(parents=True, exist_ok=True)
    save_json(report, result)
    try:
        manifest_digest = bind(inputs, MANIFEST_PATH)
        manifest = load_json(MANIFEST_PATH)
        require(manifest.get("schema") == "z100-staged-packer-integration-candidate/1" and
                manifest.get("status") == "COMPONENT_VERIFIED_READY_FOR_FULL_CORE_INTEGRATION_ONLY",
                "staged-packer integration-candidate manifest status")
        require(manifest.get("part") == PART and manifest.get("clock_period_ns") == PERIOD_NS and
                manifest.get("spatial_sites") == 20, "staged-packer design identity")
        require(manifest.get("full_core_rtl_integration_accepted") is False and
                manifest.get("full_core_timing_accepted") is False and manifest.get("physical_fps") is None,
                "candidate manifest must remain integration-only")
        overrides = manifest.get("source_overrides", [])
        require(len(overrides) == 1 and overrides[0].get("original") ==
                "build/v12p_d46da432/rtl/z100_native_output_packer.sv" and
                overrides[0].get("replacement") == v12.project_name(PACKER_PATH) and
                overrides[0].get("replacement_sha256") == EXPECTED_PACKER_SHA256,
                "manifest must pin exactly one output-packer replacement")
        bind(inputs, PACKER_PATH, EXPECTED_PACKER_SHA256)
        frozen_packer = FROZEN_RTL / "z100_native_output_packer.sv"
        bind(inputs, frozen_packer, EXPECTED_FROZEN_PACKER_SHA256)
        require(VENDOR.joinpath("xvlog.bat").is_file() and VENDOR.joinpath("xelab.bat").is_file() and
                VENDOR.joinpath("xsim.bat").is_file() and VIVADO.is_file(), "Vivado 2026.1 tools missing")
        for item in manifest.get("evidence", []):
            bind(inputs, v12.resolve(item["path"]), item["sha256"])
        identity = manifest["source_identity"]
        bind(inputs, v12.resolve(identity["path"]), identity["sha256"])
        package_path = v12.resolve(EXPECTED_PACKAGE_PATH)
        bind(inputs, package_path, EXPECTED_PACKAGE_SHA256)
        model_id_path = v12.resolve(EXPECTED_MODEL_ID_REPORT)
        model_id = load_json(model_id_path)
        require(model_id.get("status") == "PASS_OFFLINE_ACCELERATOR_STAGE_NOT_FULLGRAPH_OR_BOARD" and
                model_id.get("model_identity") == EXPECTED_MODEL_ID,
                "epoch200 PIN640 package ancestry report/model identity")
        bind(inputs, model_id_path)

        primary, ownership, numeric, core, baseline_markers = v12route.validate_proofs(inputs)
        v10_path = v12.resolve(EXPECTED_V10_PROOF)
        v10 = load_json(v10_path)
        require(v10.get("source_package_sha256") == EXPECTED_PACKAGE_SHA256 and
                v10.get("status") == v12.CORE_V10_STATUS,
                "V12 numerical ancestry does not match the verified epoch200 package")
        bind(inputs, v10_path, EXPECTED_V10_PROOF_SHA256)
        bind(inputs, Path(__file__))
        bind(inputs, Path(v12.__file__))
        bind(inputs, Path(v12route.__file__))
        bind(inputs, Path(route_review.__file__))
        bind(inputs, VIVADO)
        result["model_ancestry"] = {
            "intended_only_not_accuracy_acceptance": True,
            "model_identity": EXPECTED_MODEL_ID,
            "package_path": EXPECTED_PACKAGE_PATH,
            "package_sha256": EXPECTED_PACKAGE_SHA256,
            "package_identity_report": v12.project_name(model_id_path),
            "package_identity_report_sha256": sha256_file(model_id_path),
            "verified_v10_numerical_ancestry_report": EXPECTED_V10_PROOF,
            "verified_v10_numerical_ancestry_report_sha256": EXPECTED_V10_PROOF_SHA256,
            "v12_numeric_report_does_not_claim_model_accuracy": True,
        }

        manifest_sources = manifest.get("original_source_closure", [])
        require(len(manifest_sources) == 28, "integration manifest must pin exactly 28 original RTL files")
        # The old CORE_PREP has different directories and predates the V12
        # adapter/top substitutions. Bind the accepted V12 compile closure by
        # content, not by historical generated-path spelling.
        accepted_core = [v12.resolve(name) for name in numeric["commands"][0]["argv"][2:]
                         if v12.resolve(name).parent.name == "rtl"]
        require(len(accepted_core) == 28, "accepted V12 numeric RTL count changed")
        require({sha256_file(path) for path in accepted_core} ==
                {item["sha256"] for item in manifest_sources},
                "manifest hashes differ from accepted V12 numerical closure")
        for item in manifest_sources:
            bind(inputs, v12.resolve(item["path"]), item["sha256"])

        # Keep the accepted validator's staging behavior and then add only the
        # explicitly reviewed E0-E4 timing adaptation plus the one RTL override.
        prep, baseline, core_again, baseline_markers = v12.load_numeric_inputs(inputs)
        require(core_again == core, "numeric proof/core preparation changed during setup")
        compile_files, tb_name, rewrites = v12.prepare_numeric(build, output, inputs, artifacts, prep, core)
        staged_core = [path for path in compile_files if path.parent.name == "rtl"]
        require(len(staged_core) == 28 and {sha256_file(path) for path in staged_core} ==
                {item["sha256"] for item in manifest_sources},
                "V12 staged RTL does not reproduce the frozen implementation before override")
        staged_numeric_tb = next(path for path in compile_files if path.name == tb_name + ".sv")
        tb_text = staged_numeric_tb.read_text(encoding="utf-8")
        require(tb_text.count(NUMERIC_TB_REWRITE_FROM) == 1,
                "original numeric TB config_packer rewrite point must occur once")
        tb_text = tb_text.replace(NUMERIC_TB_REWRITE_FROM, NUMERIC_TB_REWRITE_TO, 1)
        staged_numeric_tb.write_text(tb_text, encoding="utf-8", newline="\n")
        artifacts[v12.project_name(staged_numeric_tb)] = sha256_file(staged_numeric_tb)

        packer_targets = [path for path in compile_files if path.name == "z100_native_output_packer.sv"]
        require(len(packer_targets) == 1 and sha256_file(packer_targets[0]) == EXPECTED_FROZEN_PACKER_SHA256,
                "numeric compile must stage exactly one frozen packer before override")
        copy_verified(PACKER_PATH, packer_targets[0], artifacts)
        require(sha256_file(packer_targets[0]) == EXPECTED_PACKER_SHA256,
                "staged packer override hash")
        staged_packer_text = packer_targets[0].read_text(encoding="utf-8")
        frozen_packer_text = frozen_packer.read_text(encoding="utf-8")
        signature = r"module\s+z100_native_output_packer.*?\);"
        old_signature = re.findall(signature, frozen_packer_text, re.S)
        new_signature = re.findall(signature, staged_packer_text, re.S)
        require(len(old_signature) == len(new_signature) == 1 and old_signature[0] == new_signature[0],
                "staged packer public module interface changed")
        module_names: list[str] = []
        for path in compile_files:
            module_names.extend(re.findall(r"(?m)^\s*module\s+([A-Za-z_]\w*)", path.read_text(encoding="utf-8", errors="replace")))
        require(module_names.count("z100_native_output_packer") == 1,
                "exactly one same-name packer module must be compiled")

        input_before = dict(sorted(inputs.items()))
        result["source_sha256_before"] = input_before
        result["staged_artifacts"] = dict(sorted(artifacts.items()))
        result["manifest_sha256"] = manifest_digest
        result["source_manifest"] = {
            "schema": "z100-staged-packer-full-core-source-manifest/1",
            "candidate_manifest": v12.project_name(MANIFEST_PATH),
            "candidate_manifest_sha256": manifest_digest,
            "part": PART,
            "top": TOP,
            "clock_period_ns": PERIOD_NS,
            "original_core_source_count": 28,
            "source_override_count": 1,
            "packer_override": {"original_sha256": EXPECTED_FROZEN_PACKER_SHA256,
                                 "replacement": v12.project_name(PACKER_PATH),
                                 "replacement_sha256": EXPECTED_PACKER_SHA256,
                                 "staged": v12.project_name(packer_targets[0])},
            "numeric_testbench_rewrites": rewrites + [{
                "kind": "staged configuration timing adaptation only",
                "from": NUMERIC_TB_REWRITE_FROM,
                "to": NUMERIC_TB_REWRITE_TO,
                "purpose": "Check E0 acceptance, remain pending at E1-E3, and become active at E4; deassert cfg_valid at the first negedge after E0.",
                "product_rtl_changed": False,
            }],
            "compile_sources": [v12.project_name(path) for path in compile_files],
            "compile_source_count": len(compile_files),
            "unique_packer_module_count": module_names.count("z100_native_output_packer"),
        }
        result["numeric_baseline_report"] = v12.project_name(v12.BASE_NUMERIC)
        result["numeric_baseline_report_sha256"] = sha256_file(v12.BASE_NUMERIC)
        result["numeric_baseline_markers"] = baseline_markers
        result["numeric_compile_files"] = [v12.project_name(path) for path in compile_files]
        result["numeric_testbench"] = v12.project_name(staged_numeric_tb)
        result["numeric_testbench_sha256"] = sha256_file(staged_numeric_tb)
        result["status"] = "READY_FOR_ORIGINAL_GOLDEN_XSIM"
        result["checks"].extend([
            {"check": "exact_28_source_frozen_closure_plus_one_packer_override", "status": "PASS"},
            {"check": "same_name_packer_unique_and_interface_identical", "status": "PASS"},
            {"check": "numeric_tb_e0_e4_timing_adaptation_only", "status": "PASS"},
            {"check": "epoch200_pin640_identity_ancestry", "status": "PASS_IDENTITY_ONLY"},
        ])
        update_artifacts(result)
        persist(result)
        return result, report
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        result["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        result["source_sha256_before"] = dict(sorted(inputs.items()))
        refresh_source_after(result)
        update_artifacts(result)
        persist(result)
        return result, report


def load_run(report: Path) -> dict[str, Any]:
    report = report.resolve(strict=True)
    require(report.is_relative_to(OUT_ROOT.resolve()), "resume report escapes staged-packer validation root")
    result = load_json(report)
    require(result.get("schema") == "z100-staged-packer-full-core-integration/1" and
            v12.resolve(result["report"]) == report, "resume report schema/path")
    require(result.get("source_sha256_before"), "resume source bindings are empty")
    for name, expected in result["source_sha256_before"].items():
        require(sha256_file(v12.resolve(name)) == expected, f"resume source drift: {name}")
    for name, expected in result.get("artifact_sha256", {}).items():
        require(sha256_file(v12.resolve(name)) == expected, f"resume artifact drift: {name}")
    return result


def stage_paths(result: dict[str, Any]) -> tuple[Path, Path, Path]:
    out = v12.resolve(result["run_directory"])
    build = v12.resolve(result["build_directory"])
    report = v12.resolve(result["report"])
    require(out.is_dir() and build.is_dir(), "run output/build directory missing")
    return out, build, report


def run_numeric(result: dict[str, Any]) -> None:
    require(result.get("numeric_status") is None, "numeric suite already has a terminal result")
    out, build, report = stage_paths(result)
    compile_files = [v12.resolve(name) for name in result["numeric_compile_files"]]
    require(len(compile_files) == 32, "numeric simulation must compile the exact 28 core + 4 golden support files")
    require(sha256_file(v12.resolve(result["numeric_testbench"])) == result["numeric_testbench_sha256"],
            "staged numeric testbench changed before simulation")
    require(sha256_file(next(path for path in compile_files if path.name == "z100_native_output_packer.sv")) == EXPECTED_PACKER_SHA256,
            "staged numeric compile packer identity")
    mutex = VendorMutex()
    try:
        v12.require_quiescent()
        result["vendor_mutex"] = mutex.acquire()
        result["vendor_state_at_start"] = v12.process_inventory()
        xvlog = VENDOR / "xvlog.bat"
        xelab = VENDOR / "xelab.bat"
        xsim = VENDOR / "xsim.bat"
        run_vendor_command(result, "numeric_xvlog", [xvlog, "-sv", *compile_files], build, out / "numeric_xvlog.log")
        snapshot = "spc_num_" + re.sub(r"\W", "", result["run_id"])
        elaborate = [xelab, "-mt", "2", "-L", "unimacro_ver", "-L", "unisims_ver",
                     "glbl", v12.NEW_TB_NAME, "-s", snapshot]
        run_vendor_command(result, "numeric_xelab", elaborate, build, out / "numeric_xelab.log")
        sim_text = run_vendor_command(result, "numeric_xsim", [xsim, snapshot, "-runall"], build, out / "numeric_xsim.log")
        actual = marker_lines(sim_text)
        comparison = compare_numeric_markers(result["numeric_baseline_markers"], actual)
        result["original_golden_comparison"] = comparison
        result["numeric_status"] = "PASS_STAGED_PACKER_ORIGINAL_GOLDEN_XSIM_ONLY"
        result["run_steps"]["numeric"] = {"status": result["numeric_status"],
                                             "markers": actual,
                                             "compile_source_count": len(compile_files),
                                             "control_scope": "Original frozen Conv/Pool/retained-Conv numerical fixtures; marker invariants exact except the five explicitly whitelisted scheduling counters."}
        result["checks"].append({"check": "original_golden_numeric_markers", "status": "PASS",
                                 "allowed_timing_counter_differences": comparison["timing_counter_differences"]})
        result["status"] = "PASS_NUMERIC_AWAITING_DIRECTED_CONTROL"
    except Exception as exc:
        result["numeric_status"] = "FAILED_CLOSED"
        result["status"] = "FAILED_CLOSED"
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        result["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        mutex.release()
        refresh_source_after(result)
        update_artifacts(result)
        persist(result)


def prepare_control_tb(result: dict[str, Any], build: Path, artifacts: dict[str, str]) -> tuple[Path, str, str]:
    require(CONTROL_TB_PATH.is_file(), f"directed-control testbench is not ready: {v12.project_name(CONTROL_TB_PATH)}")
    inputs = result["source_sha256_before"]
    tb_digest = bind(inputs, CONTROL_TB_PATH)
    text = CONTROL_TB_PATH.read_text(encoding="utf-8")
    declarations = re.findall(r"(?m)^\s*module\s+([A-Za-z_]\w*)", text)
    require(len(declarations) == 1, "directed-control TB must declare exactly one simulation top")
    tb_top = declarations[0]
    require(text.count(TOP) >= 1, f"directed-control TB does not instantiate the full V12 top {TOP}")
    pass_displays = re.findall(r"\$display\s*\(\s*\"([^\"]*PASS[^\"]*)\"", text)
    require(len(pass_displays) == 1, "directed-control TB must expose exactly one PASS display")
    pass_tag = pass_displays[0].split()[0]
    staged = copy_verified(CONTROL_TB_PATH, build / "tb_z100_staged_packer_core_control.sv", artifacts)
    result["source_sha256_before"] = dict(sorted(inputs.items()))
    result["directed_control_testbench"] = {
        "source": v12.project_name(CONTROL_TB_PATH), "source_sha256": tb_digest,
        "staged": v12.project_name(staged), "staged_sha256": sha256_file(staged),
        "top": tb_top, "expected_pass_tag": pass_tag,
        "source_contains_full_v12_top": True,
    }
    return staged, tb_top, pass_tag


def run_control(result: dict[str, Any]) -> None:
    require(result.get("numeric_status") == "PASS_STAGED_PACKER_ORIGINAL_GOLDEN_XSIM_ONLY",
            "directed control must run only after the original-golden numeric suite passes")
    require(result.get("control_status") is None, "directed-control suite already has a terminal result")
    out, build, report = stage_paths(result)
    artifacts = dict(result.get("staged_artifacts", {}))
    staged_tb, tb_top, pass_tag = prepare_control_tb(result, build, artifacts)
    original_files = [v12.resolve(name) for name in result["numeric_compile_files"]]
    numeric_tb = v12.resolve(result["numeric_testbench"])
    require(numeric_tb in original_files, "numeric TB not present in preserved 32-source compile list")
    compile_files = [staged_tb if path == numeric_tb else path for path in original_files]
    require(len(compile_files) == 32 and sum(path == staged_tb for path in compile_files) == 1,
            "directed-control compile closure must replace only the numeric TB")
    mutex = VendorMutex()
    try:
        v12.require_quiescent()
        result["vendor_mutex"] = mutex.acquire()
        result["vendor_state_at_start"] = v12.process_inventory()
        xvlog = VENDOR / "xvlog.bat"
        xelab = VENDOR / "xelab.bat"
        xsim = VENDOR / "xsim.bat"
        run_vendor_command(result, "control_xvlog", [xvlog, "-sv", *compile_files], build, out / "control_xvlog.log")
        snapshot = "spc_ctrl_" + re.sub(r"\W", "", result["run_id"])
        elaborate = [xelab, "-mt", "2", "-L", "unimacro_ver", "-L", "unisims_ver",
                     "glbl", tb_top, "-s", snapshot]
        run_vendor_command(result, "control_xelab", elaborate, build, out / "control_xelab.log")
        sim_text = run_vendor_command(result, "control_xsim", [xsim, snapshot, "-runall"], build, out / "control_xsim.log")
        pass_rows = [line.strip() for line in sim_text.splitlines() if line.strip().startswith(pass_tag)]
        require(len(pass_rows) == 1, f"directed-control simulation must emit exactly one {pass_tag} marker")
        _, counters = parse_marker(pass_rows[0])
        require(counters, "directed-control PASS marker must report its exact counters")
        result["control_status"] = "PASS_STAGED_PACKER_FULL_TOP_DIRECTED_CONTROL_XSIM_ONLY"
        result["run_steps"]["directed_control"] = {
            "status": result["control_status"], "marker": pass_rows[0], "counters": counters,
            "compile_source_count": len(compile_files),
            "control_scope": "Full frozen V12 top with candidate packer; exact directed ownership, early-run/config staging, metadata/post backpressure, invalid-config error, and cancel/reload coverage is defined by the bound testbench.",
        }
        result["staged_artifacts"] = dict(sorted(artifacts.items()))
        result["checks"].append({"check": "full_top_directed_control_exact_marker", "status": "PASS",
                                 "marker": pass_rows[0]})
        result["status"] = "PASS_SIMULATIONS_AWAITING_FULL_CORE_ROUTE"
    except Exception as exc:
        result["control_status"] = "FAILED_CLOSED"
        result["status"] = "FAILED_CLOSED"
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        result["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        mutex.release()
        refresh_source_after(result)
        update_artifacts(result)
        persist(result)


def make_route_tcl(out: Path, build: Path, sources: list[Path]) -> str:
    read_sources = " ".join(tcl_path(path) for path in sources)
    lines = [
        f"set_param general.maxThreads {SYNTH_THREADS}",
        'if {![string match 2026.1* [version -short]]} {error "Requires Vivado 2026.1"}',
        f"read_verilog -sv {read_sources}",
        f"synth_design -top {TOP} -part {PART} -mode out_of_context -flatten_hierarchy none",
        f"create_clock -name row_clk -period {PERIOD_NS:g} [get_ports clk]",
        "opt_design",
        "proc staged_core_screen {stage resource_file} {",
        "    set clocks [get_clocks -quiet]",
        '    if {[llength $clocks] != 1} {error "staged core requires one row_clk"}',
        '    if {[get_property NAME $clocks] ne "row_clk" || [get_property PERIOD $clocks] != 10.0} {error "staged core clock contract changed"}',
        "    set leaf [get_cells -hier -filter {IS_PRIMITIVE == 1}]",
        "    set dsp [llength [get_cells -quiet -hier -filter {REF_NAME == DSP48E1}]]",
        "    set latches [llength [filter $leaf REF_NAME=~LD*]]",
        "    set blackboxes [llength [get_cells -quiet -hier -filter {IS_BLACKBOX == 1}]]",
        '    puts "STAGED_CORE_RESOURCE stage=$stage dsp=$dsp latches=$latches blackboxes=$blackboxes"',
        '    set f [open $resource_file a]',
        '    puts $f "$stage\t$dsp\t$latches\t$blackboxes"',
        '    close $f',
        '    if {$dsp != 2016 || $latches != 0 || $blackboxes != 0} {error "staged core resource gate failed at $stage"}',
        "}",
        "# Preserve a post-synthesis checkpoint before optional reports.",
        "write_checkpoint -force " + tcl_path(build / "post_synth.dcp"),
        "staged_core_screen synth " + tcl_path(out / "resource_stages.tsv"),
        "report_timing_summary -delay_type min_max -report_unconstrained -file " + tcl_path(out / "timing_synth.rpt"),
        "report_utilization -file " + tcl_path(out / "utilization_synth.rpt"),
        f'puts "STAGED_CORE_STAGE_COMPLETE stage=synth synth_threads={SYNTH_THREADS}"',
        f"set_param general.maxThreads {IMPLEMENTATION_THREADS}",
        "place_design -directive Default",
        "write_checkpoint -force " + tcl_path(build / "post_place.dcp"),
        "staged_core_screen place " + tcl_path(out / "resource_stages.tsv"),
        "report_timing_summary -delay_type min_max -report_unconstrained -file " + tcl_path(out / "timing_placed.rpt"),
        "report_utilization -file " + tcl_path(out / "utilization_placed.rpt"),
        "report_design_analysis -congestion -file " + tcl_path(out / "congestion_placed.rpt"),
        f'puts "STAGED_CORE_STAGE_COMPLETE stage=place implementation_threads={IMPLEMENTATION_THREADS}"',
        "phys_opt_design -hold_fix",
        "write_checkpoint -force " + tcl_path(build / "pre_route.dcp"),
        "staged_core_screen pre_route_physopt " + tcl_path(out / "resource_stages.tsv"),
        "report_timing_summary -delay_type min_max -report_unconstrained -file " + tcl_path(out / "timing_pre_route.rpt"),
        "report_drc -checks [get_drc_checks LUTLP-1] -file " + tcl_path(out / "loop_pre_route.rpt"),
        f'puts "STAGED_CORE_STAGE_COMPLETE stage=pre_route_physopt hold_fix=1"',
        "route_design -directive Default",
        "write_checkpoint -force " + tcl_path(build / "post_route.dcp"),
        "staged_core_screen route " + tcl_path(out / "resource_stages.tsv"),
        "report_route_status -file " + tcl_path(out / "route_status.rpt"),
        "report_timing_summary -delay_type min_max -report_unconstrained -file " + tcl_path(out / "timing_routed.rpt"),
        "report_timing -delay_type max -max_paths 50 -path_type full_clock_expanded -file " + tcl_path(out / "setup_paths_routed.rpt"),
        "report_timing -delay_type min -max_paths 50 -path_type full_clock_expanded -file " + tcl_path(out / "hold_paths_routed.rpt"),
        "report_pulse_width -file " + tcl_path(out / "pulse_width_routed.rpt"),
        "report_utilization -file " + tcl_path(out / "utilization_routed.rpt"),
        "report_design_analysis -congestion -file " + tcl_path(out / "congestion_routed.rpt"),
        "report_drc -checks [get_drc_checks LUTLP-1] -file " + tcl_path(out / "loop_routed.rpt"),
        "report_drc -file " + tcl_path(out / "drc_routed.rpt"),
        "set timing_checks [check_timing -verbose -return_string]",
        "set f [open " + tcl_path(out / "check_timing_routed.rpt") + " w]",
        "puts $f $timing_checks",
        "close $f",
        f'puts "STAGED_PACKER_CORE_ROUTE_COMPLETE version=[version -short] part={PART} period_ns={PERIOD_NS:g} synth_threads={SYNTH_THREADS} implementation_threads={IMPLEMENTATION_THREADS} pblock=none"',
        "exit",
    ]
    return "\n".join(lines) + "\n"


def inspect_route(result: dict[str, Any], out: Path, build: Path, log_text: str) -> dict[str, Any]:
    complete_marker = re.findall(r"^STAGED_PACKER_CORE_ROUTE_COMPLETE\b.*$", log_text, re.M)
    require(len(complete_marker) == 1, "full-core route completion marker")
    resource_lines = (out / "resource_stages.tsv").read_text(encoding="utf-8").splitlines()
    resource_stages = []
    for line in resource_lines:
        fields = line.split("\t")
        require(len(fields) == 4, f"malformed resource census: {line}")
        resource_stages.append({"stage": fields[0], "dsp48e1": int(fields[1]),
                                "latches": int(fields[2]), "blackboxes": int(fields[3])})
    require([row["stage"] for row in resource_stages] == ["synth", "place", "pre_route_physopt", "route"],
            "resource census missing a full-core implementation stage")
    route_values: dict[str, Any] = {}
    route_error = None
    timing_error = None
    try:
        route_values = route_review.parse_route((out / "route_status.rpt").read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        route_error = f"{type(exc).__name__}: {exc}"
    timing_values: dict[str, Any] = {}
    try:
        timing_values = route_review.parse_timing((out / "timing_routed.rpt").read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        timing_error = f"{type(exc).__name__}: {exc}"
    drc_text = (out / "drc_routed.rpt").read_text(encoding="utf-8", errors="replace")
    loop_text = (out / "loop_routed.rpt").read_text(encoding="utf-8", errors="replace")
    drc_errors = len(re.findall(r"(?m)^\s*\S+#\d+\s+Error\b", drc_text))
    loop_critical = bool(re.search(r"(?m)^LUTLP-1#\d+\s+Critical Warning\b", loop_text))
    legal = route_error is None and drc_errors == 0
    timing_passed = timing_error is None and timing_values.get("internal_timing_passed") is True
    resources_passed = all(row["dsp48e1"] == 2016 and row["latches"] == 0 and row["blackboxes"] == 0
                           for row in resource_stages)
    route_status = "PASS_LEGAL_ROUTE_INTERNAL_TIMING" if legal and timing_passed and resources_passed and not loop_critical else (
        "FAIL_TIMING" if legal and route_error is None and not timing_passed else "FAIL_ROUTE_OR_RESOURCE_GATE")
    result["route_completion_marker"] = complete_marker[0]
    result["resource_stages"] = resource_stages
    result["route_metrics"] = route_values
    result["timing_metrics"] = timing_values
    result["route_parse_error"] = route_error
    result["timing_parse_error"] = timing_error
    result["drc_error_count"] = drc_errors
    result["unwaived_lutlp_critical_warning"] = loop_critical
    result["route_status"] = route_status
    result["route_acceptance"] = {
        "legal_route": legal,
        "internal_setup_hold_pulse_timing_passed": timing_passed,
        "resource_gate_passed": resources_passed,
        "clock_period_ns": PERIOD_NS,
        "external_io_paths_constrained": False,
        "board_timing_or_fps_accepted": False,
    }
    return result["route_acceptance"]


def run_route(result: dict[str, Any]) -> None:
    require(result.get("numeric_status") == "PASS_STAGED_PACKER_ORIGINAL_GOLDEN_XSIM_ONLY" and
            result.get("control_status") == "PASS_STAGED_PACKER_FULL_TOP_DIRECTED_CONTROL_XSIM_ONLY",
            "full-core route requires both serialized simulation suites to pass")
    require(result.get("route_status") is None, "full-core route already has a terminal result")
    out, build, report = stage_paths(result)
    try:
        resources = v12.require_system_resources()
        result["system_resources_at_launch"] = resources
        source_manifest = result["source_manifest"]
        # Simulation-only reference/bind observers, testbench and glbl must
        # never enter hardware synthesis. Only the28 staged core RTL files do.
        compile_files = [v12.resolve(name) for name in source_manifest["compile_sources"]
                         if v12.resolve(name).parent.name == "rtl"]
        require(len(compile_files) == 28, "full-core synthesis must contain exactly28 core RTL sources")
        for path in compile_files:
            require(path.is_file(), f"route source missing: {path}")
        require(sha256_file(next(path for path in compile_files if path.name == "z100_native_output_packer.sv")) == EXPECTED_PACKER_SHA256,
                "full-core route packer source identity")
        route_tcl = out / "full_core_route.tcl"
        route_tcl.write_text(make_route_tcl(out, build, compile_files), encoding="utf-8", newline="\n")
        result["staged_artifacts"][v12.project_name(route_tcl)] = sha256_file(route_tcl)
        result["source_sha256_before"] = dict(sorted(result["source_sha256_before"].items()))
        result["status"] = "RUNNING_FULL_CORE_SYNTH_PLACE_PHYSOPT_ROUTE"
        result["route_command"] = [str(VIVADO), "-mode", "batch", "-source", str(route_tcl)]
        persist(result)

        mutex = VendorMutex()
        try:
            v12.require_quiescent()
            result["vendor_mutex"] = mutex.acquire()
            result["vendor_state_at_start"] = v12.process_inventory()
            route_log_text = run_vendor_command(result, "full_core_vivado", result["route_command"], build,
                                                out / "vivado_route.log", heartbeat_seconds=15)
        finally:
            mutex.release()

        route_acceptance = inspect_route(result, out, build, route_log_text)
        result["run_steps"]["full_core_implementation"] = {
            "status": result["route_status"], "route_acceptance": route_acceptance,
            "synthesis_max_threads": SYNTH_THREADS,
            "implementation_max_threads": IMPLEMENTATION_THREADS,
            "route_directive": "Default", "pre_route_phys_opt": "phys_opt_design -hold_fix",
            "constraint_set": "single 10 ns row_clk only, no I/O delay, no Pblock",
            "fresh_synthesis": True, "resumed_old_checkpoint": False,
        }
        result["synthesis_or_route_accepted"] = result["route_status"] == "PASS_LEGAL_ROUTE_INTERNAL_TIMING"
        result["status"] = result["route_status"]
        result["checks"].append({"check": "full_core_route_timing_resource_and_drc", "status": result["route_status"],
                                 "route_metrics": result.get("route_metrics"),
                                 "timing_metrics": result.get("timing_metrics")})
    except Exception as exc:
        result["route_status"] = "FAILED_CLOSED"
        result["status"] = "FAILED_CLOSED"
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        result["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        refresh_source_after(result)
        update_artifacts(result)
        persist(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("numeric", "control", "route", "all"), default="numeric")
    parser.add_argument("--resume", type=Path, help="continue the exact report produced by an earlier stage")
    args = parser.parse_args(argv)

    result: dict[str, Any]
    report: Path
    if args.resume is None:
        require(args.stage in ("numeric", "all"), "a new run must start with --stage numeric or --stage all")
        result, report = prepare_run()
        if result.get("status") == "FAILED_CLOSED":
            print(json.dumps({"status": result["status"], "report": v12.project_name(report),
                              "errors": result["errors"]}))
            return 1
    else:
        report = args.resume.resolve(strict=True)
        result = load_run(report)

    try:
        if args.stage in ("numeric", "all") and result.get("numeric_status") is None:
            run_numeric(result)
        if args.stage in ("control", "all") and result.get("control_status") is None:
            if not CONTROL_TB_PATH.is_file():
                result["status"] = "PASS_NUMERIC_AWAITING_DIRECTED_CONTROL_TB"
                result["control_wait_path"] = v12.project_name(CONTROL_TB_PATH)
                persist(result)
                print(json.dumps({"status": result["status"], "report": result["report"],
                                  "control_tb": result["control_wait_path"]}))
                return 0
            run_control(result)
        if args.stage in ("route", "all") and result.get("route_status") is None:
            run_route(result)
    except Exception as exc:
        print(json.dumps({"status": result.get("status"), "report": result.get("report"),
                          "error": f"{type(exc).__name__}: {exc}"}))
        return 1

    refresh_source_after(result)
    update_artifacts(result)
    persist(result)
    print(json.dumps({"status": result.get("status"), "run_id": result.get("run_id"),
                      "report": result.get("report"), "build": result.get("build_directory"),
                      "numeric_status": result.get("numeric_status"),
                      "control_status": result.get("control_status"),
                      "route_status": result.get("route_status")}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RunError as exc:
        print(json.dumps({"status": "FAILED_PREFLIGHT", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(2)
