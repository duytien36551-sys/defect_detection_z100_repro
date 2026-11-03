"""Run the isolated V12 descriptor ownership oracle or original-golden proof."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "deployment/hardware/z100_2026"
V12 = HW / "feature_input_capture_v12"
OUT_ROOT = ROOT / "validation/board_z100/feature_input_capture_v12"
PYTHON = Path("C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe")
VENDOR = Path("C:/appload/2026.1/Vivado/bin")
VENDOR_NAMES = {"vivado.exe", "xvlog.exe", "xelab.exe", "xsim.exe", "xsimk.exe", "xvhdl.exe", "xsc.exe"}
WAITER_MARKERS = (
    "route_z100_local_control_recovery_v1.py",
    "run_z100_locality_numeric_after_",
    "run_z100_native_mmio_local_control_platform_v2.py",
)
PLATFORM_LOCK = ROOT / "validation/board_z100/native_mmio_local_control_platform_v2/.vivado.lock"

BASE_PREP = ROOT / "validation/board_z100/locality_numeric_v1/local_control_v1/20261026T101524.394808Z/result.json"
BASE_PREP_SHA256 = "f88f8531ce1f9f19855e44f46075fb2f850b0d313a15b06536090c0ed600e065"
BASE_NUMERIC = ROOT / "validation/board_z100/locality_numeric_recovery_serial_v2/20261026T132421.824404Z/result.json"
BASE_NUMERIC_SHA256 = "910c091d8634a6ec83793ab58b9471d63800adfc2a7d174fc0f6a3d475b180f2"
CORE_PREP = ROOT / "validation/board_z100/mac_local_control_core_v1/20261026T084049.798285Z/result.json"
CORE_PREP_SHA256 = "437cf9314192f1bcafc1a6b14ecdabea9629ade55a02662071012d6d9fe4f669"
CORE_V10_PROOF = "validation/board_z100/feature_address_shared_v10_compute/20261025T190545.372805Z/result.json"
CORE_V10_STATUS = "PASS_PRIVATE_ADDRESS_SHARED_V10_SHARED_AXI_FULL20SITE_ORIGINAL_POOL_MITER_CONV_RETAINED_DDR_GOLDEN_XSIM_ONLY"
CORE_CLOSURE_SHA256 = "489c5edc846a30445e6ae1d108ec628afd32712c8b618685a8f1b2112cd46daa"
ADAPTER_SOURCE = "deployment/hardware/z100_2026/feature_address_shared_v10/z100_feature_window20_address_shared_v10.sv"
TOP_SOURCE = "deployment/hardware/z100_2026/feature_address_shared_v10/z100_native_row20_shared_pool_address_shared_v10.sv"
ADAPTER_V12 = V12 / "z100_feature_window20_address_shared_v12.sv"
TOP_V12 = V12 / "z100_native_row20_shared_pool_address_shared_local_control_v12.sv"
OWNERSHIP_TB = V12 / "tb_z100_feature_input_capture_v12_ownership.sv"
OLD_TB_NAME = "tb_z100_locality_numeric_v1"
NEW_TB_NAME = "tb_z100_feature_input_capture_v12_numeric"
OLD_TOP_NAME = "z100_native_row20_shared_pool_address_shared_local_control_v1"
NEW_TOP_NAME = "z100_native_row20_shared_pool_address_shared_local_control_v12"

OWNERSHIP_EXPECTED = {
    "writes": 28,
    "value_mask_checks": 400,
    "verified_windows": 5,
    "bank1_verified_windows": 1,
    "held_cycles": 3,
    "bank_exclusion_hold_cycles": 2,
    "full_blocks": 2,
    "bubbles": 1,
    "simultaneous": 1,
    "invalid": 1,
    "cancel_empty": 1,
    "cancel_one": 1,
    "cancel_two": 2,
    "both_bank_pending": 1,
    "overwrite_blocks": 1,
    "reuse_after_cancel": 1,
    "cancel_attempted_pop": 1,
    "accepted_cfg_words": 28,
    "accepted_window_handshakes": 12,
    "accepted_descriptors": 11,
    "invalid_handshakes": 1,
    "enqueued_descriptors": 11,
    "popped_descriptors": 6,
    "cancel_cycles": 4,
    "cancelled_descriptors": 5,
    "simultaneous_handshakes": 1,
    "max_fifo_occupancy": 2,
}


class ValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve(name: str | Path) -> Path:
    text = str(name).replace("\\", "/")
    if text.startswith("external/C/"):
        return Path("C:/" + text[len("external/C/"):]).resolve()
    path = Path(text)
    return (path if path.is_absolute() else ROOT / path).resolve()


def project_name(path: Path) -> str:
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        text = path.as_posix()
        require(len(text) > 2 and text[1:3] == ":/", "external path is not drive qualified")
        return "external/" + text[0] + text[2:]


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def verify_hash_map(mapping: dict[str, str], label: str) -> None:
    require(isinstance(mapping, dict) and mapping, f"{label} hash map is empty")
    for name, digest in mapping.items():
        path = resolve(name)
        require(path.is_file() and sha256_file(path) == digest, f"{label} hash mismatch: {name}")


def bind(bindings: dict[str, str], path: Path, expected: str | None = None) -> str:
    path = Path(path).resolve()
    require(path.is_file(), f"bound input missing: {path}")
    digest = sha256_file(path)
    require(expected is None or digest == expected, f"bound input hash mismatch: {path}")
    name = project_name(path)
    require(name not in bindings or bindings[name] == digest, f"conflicting hash for {name}")
    bindings[name] = digest
    return digest


def input_map(paths: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in paths:
        bind(result, path)
    return dict(sorted(result.items()))


def process_inventory() -> list[dict[str, Any]]:
    query = (
        "$ErrorActionPreference='Stop'; "
        "@(Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine) "
        "| ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", query],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValidationError(f"cannot inspect vendor process inventory: {exc}") from exc
    if not completed.stdout.strip():
        return []
    rows = json.loads(completed.stdout)
    if rows is None:
        return []
    return rows if isinstance(rows, list) else [rows]


def require_quiescent() -> list[dict[str, Any]]:
    require(not PLATFORM_LOCK.exists(), f"V2 Vivado lock is active: {PLATFORM_LOCK}")
    conflicts = []
    for row in process_inventory():
        name = str(row.get("Name", "")).lower()
        command_line = str(row.get("CommandLine", "")).lower()
        if name in VENDOR_NAMES or any(marker in command_line for marker in WAITER_MARKERS):
            conflicts.append({"pid": row.get("ProcessId"), "name": name,
                              "command_line": row.get("CommandLine")})
    require(not conflicts, f"vendor or route/numeric owner is active: {conflicts}")
    return conflicts


def create_run_dirs(suite: str) -> tuple[str, Path, Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_id = stamp + "_" + secrets.token_hex(3)
    output = OUT_ROOT / suite / run_id
    build_name = ("v12own_" if suite == "ownership" else "v12num_") + stamp.replace(".", "")
    build = ROOT / "build" / build_name
    output.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    return run_id, output, build, output / "result.json"


def save_result(path: Path, result: dict[str, Any]) -> None:
    serializable = {key: value for key, value in result.items() if key != "report_path_obj"}
    path.write_text(json.dumps(serializable, indent=2) + "\n", encoding="utf-8", newline="\n")


def run_command(label: str, argv: list[str], cwd: Path, output: Path,
                result: dict[str, Any]) -> str:
    require_quiescent()
    log_path = output / f"{label}.log"
    env = dict(os.environ, XILINX_LOCAL_USER_DATA="no", OMP_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    try:
        completed = subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValidationError(f"cannot launch {label}: {exc}") from exc
    text = completed.stdout + completed.stderr
    log_path.write_text(text, encoding="utf-8", newline="\n")
    entry = {"label": label, "argv": argv, "cwd": project_name(cwd),
             "return_code": completed.returncode, "log": project_name(log_path),
             "log_sha256": sha256_file(log_path)}
    result["commands"].append(entry)
    save_result(result["report_path_obj"], result)
    require(completed.returncode == 0, f"{label} returned {completed.returncode}; see {log_path}")
    require(not re.search(r"^\s*(?:ERROR:|Fatal:)", text, re.MULTILINE),
            f"{label} emitted a fatal diagnostic; see {log_path}")
    require_quiescent()
    return text


def stage_copy(source: Path, target: Path, artifacts: dict[str, str]) -> Path:
    source = Path(source).resolve()
    target = Path(target).resolve()
    require(source.is_file(), f"stage source missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    digest = sha256_file(source)
    require(sha256_file(target) == digest, f"byte-identical staging failed: {source}")
    artifacts[project_name(target)] = digest
    return target


def marker_values(text: str, marker: str) -> dict[str, int]:
    rows = re.findall(r"^" + re.escape(marker) + r"\s+(.+)$", text, re.MULTILINE)
    require(len(rows) == 1, f"expected exactly one {marker} line, found {len(rows)}")
    return {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", rows[0])}


def prepare_ownership(build: Path, inputs: dict[str, str], artifacts: dict[str, str]) -> tuple[list[Path], str]:
    source_paths = [
        HW / "feature_writepipe_v7/z100_feature_banks_writepipe_4k_v5.sv",
        HW / "feature_writepipe_v7/z100_feature_banks_4read_writepipe_4k_v5.sv",
        HW / "feature_writepipe_v7/z100_feature_banks_pingpong_writepipe_v7.sv",
        ADAPTER_V12,
        OWNERSHIP_TB,
    ]
    for source in source_paths:
        bind(inputs, source)
    staged = [stage_copy(path, build / "rtl" / path.name, artifacts) for path in source_paths]
    return staged, "tb_z100_feature_input_capture_v12_ownership"


def validate_ownership_gate(path: Path, bindings: dict[str, str]) -> dict[str, Any]:
    path = Path(path).resolve(strict=True)
    require(path.is_relative_to(OUT_ROOT.resolve()), "ownership report escapes V12 evidence root")
    report = load_json(path)
    require(report.get("suite") == "ownership" and
            report.get("status") == "PASS_V12_OWNERSHIP_XSIM_ONLY" and
            report.get("simulation") == OWNERSHIP_EXPECTED,
            "numeric suite requires a passing exact V12 ownership oracle")
    require(report.get("source_sha256_before") == report.get("source_sha256_after"),
            "ownership source hashes changed")
    for name, digest in report["source_sha256_after"].items():
        require(sha256_file(resolve(name)) == digest, f"ownership source drift: {name}")
        bindings[name] = digest
    bind(bindings, path)
    return report


def load_numeric_inputs(bindings: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[str]]:
    require(sha256_file(BASE_PREP) == BASE_PREP_SHA256, "selected original-golden preparation changed")
    require(sha256_file(BASE_NUMERIC) == BASE_NUMERIC_SHA256, "accepted serial numerical baseline changed")
    require(sha256_file(CORE_PREP) == CORE_PREP_SHA256, "28-source core preparation changed")
    prep = load_json(BASE_PREP)
    baseline = load_json(BASE_NUMERIC)
    core = load_json(CORE_PREP)
    core_v10 = core.get("v10_baseline")
    require(prep.get("schema") == "z100-locality-whole-core-numerical-preparation/1" and
            prep.get("status") == "PREPARED_WHOLE_CORE_NUMERICAL_SIMULATION_NOT_EXECUTED" and
            prep.get("execution_performed") is False, "unexpected original numerical preparation")
    require(baseline.get("status") == "PASS_REAL_WHOLE_PRIVATE_CORE_NUMERICAL_NOT_FULLGRAPH" and
            baseline.get("board_access") is False and baseline.get("fullgraph_execution_accepted") is False and
            baseline.get("full_pipeline_30fps_accepted") is False, "unexpected accepted baseline scope")
    require(core.get("schema") == "z100-local-control-core-v1-preparation/1" and
            core.get("status") == "PREPARED_LOCAL_CONTROL_CORE_V1_NOT_EXECUTED" and
            isinstance(core_v10, dict) and core_v10.get("report") == CORE_V10_PROOF and
            core_v10.get("status") == CORE_V10_STATUS and
            core_v10.get("source_closure_sha256") == CORE_CLOSURE_SHA256 and
            core_v10.get("source_closure_count") == 28 and len(core.get("source_closure", [])) == 28,
            "unexpected 28-source core closure")
    require(prep.get("source_sha256_before") == prep.get("source_sha256_after"),
            "original preparation source hashes changed")
    require(core.get("source_sha256_before") == core.get("source_sha256_after"),
            "28-source preparation hashes changed")
    verify_hash_map(prep["source_sha256_after"], "original numeric preparation source")
    verify_hash_map(prep["artifacts_sha256"], "original numeric preparation artifact")
    verify_hash_map(core["source_sha256_after"], "28-source core preparation source")
    verify_hash_map(core["artifacts_sha256"], "28-source core preparation artifact")
    for path in (BASE_PREP, BASE_NUMERIC, CORE_PREP, Path(__file__)):
        bind(bindings, path)
    markers = baseline.get("actual_pass_markers")
    require(isinstance(markers, list) and len(markers) == 7 and all(isinstance(item, str) for item in markers),
            "accepted baseline does not contain all seven original numerical markers")
    return prep, baseline, core, markers


def prepare_numeric(build: Path, output: Path, inputs: dict[str, str], artifacts: dict[str, str],
                    prep: dict[str, Any], core: dict[str, Any]) -> tuple[list[Path], str, list[dict[str, Any]]]:
    old_argv = prep["commands"]["xvlog"]["argv"]
    require(len(old_argv) >= 3 and Path(old_argv[0]).name.lower() == "xvlog.bat" and old_argv[1] == "-sv",
            "original-golden xvlog command identity")
    old_inputs = [resolve(value) for value in old_argv[2:]]
    require(len(old_inputs) == 32 and len(set(old_inputs)) == 32, "original compile closure is not 32 files")
    prepared_compile = prep.get("source_closure", [])
    require(len(prepared_compile) == 32 and
            {project_name(path) for path in old_inputs} == {item["path"] for item in prepared_compile},
            "original preparation source closure differs from its exact compile command")
    for item in prepared_compile:
        path = resolve(item["path"])
        require(path.is_file() and sha256_file(path) == item["sha256"],
                "original preparation compile source hash mismatch: " + item["path"])
    old_tb = [path for path in old_inputs if path.name == OLD_TB_NAME + ".sv"]
    pool_rowbase = [path for path in old_inputs if path.name == "z100_maxpool_window20_rowbase_v2.sv"]
    pool_miter = [path for path in old_inputs if path.name == "z100_pool_tapxy_miter.sv"]
    glbl = [path for path in old_inputs if path.name == "glbl.v"]
    require(len(old_tb) == len(pool_rowbase) == len(pool_miter) == len(glbl) == 1,
            "original testbench/Pool/glbl sources must appear exactly once")
    old_core = [path for path in old_inputs if path not in old_tb + pool_rowbase + pool_miter + glbl]
    by_source = {item["source"]: item for item in core["source_closure"]}
    require(len(old_core) == 28 and len(by_source) == 28, "28-source core staging count")
    source_names = {Path(name).name for name in by_source}
    require(len(source_names) == 28 and {path.name for path in old_core} == source_names,
            "the original numerical source list does not match the frozen 28-source closure")
    require(ADAPTER_SOURCE in by_source and TOP_SOURCE in by_source,
            "V12 replacements do not correspond to the original adapter and core top")

    core_targets: dict[str, Path] = {}
    for source_name, item in by_source.items():
        source_path = resolve(source_name)
        generated = resolve(item["generated"])
        expected_source = core["source_sha256_after"].get(source_name)
        require(expected_source is not None and sha256_file(source_path) == expected_source,
                f"frozen closure source hash mismatch: {source_name}")
        require(sha256_file(generated) == item["sha256"], f"frozen generated closure hash mismatch: {generated}")
        if source_name == ADAPTER_SOURCE:
            target = stage_copy(ADAPTER_V12, build / "rtl" / ADAPTER_V12.name, artifacts)
            bind(inputs, ADAPTER_V12)
        elif source_name == TOP_SOURCE:
            target = stage_copy(TOP_V12, build / "rtl" / TOP_V12.name, artifacts)
            bind(inputs, TOP_V12)
        else:
            target = stage_copy(generated, build / "rtl" / Path(source_name).name, artifacts)
        core_targets[Path(source_name).name] = target

    for name, expected in ((BASE_PREP, BASE_PREP_SHA256), (BASE_NUMERIC, BASE_NUMERIC_SHA256),
                           (CORE_PREP, CORE_PREP_SHA256)):
        bind(inputs, name, expected)

    source_tb = old_tb[0]
    bind(inputs, source_tb, prep["testbench_transform"]["staged_sha256"])
    tb_bytes = source_tb.read_bytes()
    old_decl = ("module " + OLD_TB_NAME + ";").encode("ascii")
    new_decl = ("module " + NEW_TB_NAME + ";").encode("ascii")
    old_top = (OLD_TOP_NAME + " #(").encode("ascii")
    new_top = (NEW_TOP_NAME + " #(").encode("ascii")
    require(tb_bytes.count(old_decl) == 1 and tb_bytes.count(old_top) == 1,
            "original-golden testbench module/top rewrite points")
    transformed = tb_bytes.replace(old_decl, new_decl, 1).replace(old_top, new_top, 1)
    require(transformed.count(b"dut.feature_window.sv[0]") == 1 and
            transformed.count(b"dut.feature_window.sv[1]") == 1,
            "original feature_window.sv[1:0] hierarchy changed")
    tb_target = build / (NEW_TB_NAME + ".sv")
    tb_target.write_bytes(transformed)
    artifacts[project_name(tb_target)] = sha256_file(tb_target)
    rewrites = [
        {"kind": "testbench module rename", "from": old_decl.decode("ascii"), "to": new_decl.decode("ascii")},
        {"kind": "top module rename", "from": old_top.decode("ascii"), "to": new_top.decode("ascii")},
    ]

    staged_extras: dict[str, Path] = {}
    for source, folder in ((pool_rowbase[0], build / "pool_reference"),
                           (pool_miter[0], build / "pool_reference"),
                           (glbl[0], build / "vendor_model_sources")):
        bind(inputs, source, prep["source_sha256_after"].get(project_name(source)))
        staged_extras[source.name] = stage_copy(source, folder / source.name, artifacts)

    fixture_paths = [resolve(item["staged"]) for item in prep.get("fixtures", [])]
    require(fixture_paths, "original-golden hex/VH fixture list is empty")
    for fixture in fixture_paths:
        bind(inputs, fixture, prep["artifacts_sha256"].get(project_name(fixture)))
        stage_copy(fixture, build / fixture.name, artifacts)

    compile_files = []
    for source in old_inputs:
        if source == old_tb[0]:
            compile_files.append(tb_target)
        elif source.name in staged_extras:
            compile_files.append(staged_extras[source.name])
        else:
            require(source.name in core_targets, f"unexpected original-golden compile source: {source}")
            compile_files.append(core_targets[source.name])
    require(len(compile_files) == 32 and len(set(compile_files)) == 32,
            "V12 numeric compile must use exactly 28 core sources and four original support sources")
    return compile_files, NEW_TB_NAME, rewrites


def finalize_hashes(result: dict[str, Any], source_before: dict[str, str],
                    output: Path, build: Path) -> None:
    result["source_sha256_before"] = dict(sorted(source_before.items()))
    after = {name: sha256_file(resolve(name)) for name in source_before}
    result["source_sha256_after"] = after
    if after != result["source_sha256_before"]:
        result["status"] = "FAILED_SOURCE_INTEGRITY"
    result["artifact_sha256"] = {
        project_name(path): sha256_file(path)
        for folder in (output, build)
        for path in folder.rglob("*") if path.is_file() and path != result["report_path_obj"]
    }
    report_path = result.pop("report_path_obj")
    result["report"] = project_name(report_path)
    save_result(report_path, result)


def run_suite(suite: str, ownership_report: Path | None) -> int:
    run_id, output, build, report_path = create_run_dirs(suite)
    result: dict[str, Any] = {
        "schema": "z100-feature-input-capture-v12-validation/1",
        "run_id": run_id,
        "suite": suite,
        "status": "PREPARING",
        "vendor_version_required": "Vivado 2026.1 XSim",
        "board_access": False,
        "synthesis_or_route_accepted": False,
        "fullgraph_execution_accepted": False,
        "full_pipeline_30fps_accepted": False,
        "commands": [],
        "checks": [],
        "source_sha256_before": {},
        "source_sha256_after": {},
        "artifact_sha256": {},
        "errors": [],
        "report_path_obj": report_path,
    }
    source_before: dict[str, str] = {}
    artifacts: dict[str, str] = {}
    save_result(report_path, result)
    try:
        require_quiescent()
        xvlog, xelab, xsim = (VENDOR / "xvlog.bat", VENDOR / "xelab.bat", VENDOR / "xsim.bat")
        require(all(path.is_file() for path in (xvlog, xelab, xsim)), "Vivado 2026.1 XSim tools are missing")
        for path in (xvlog, xelab, xsim):
            bind(source_before, path)
        bind(source_before, Path(__file__))

        if suite == "ownership":
            compile_files, top = prepare_ownership(build, source_before, artifacts)
        else:
            require(ownership_report is not None, "numeric suite requires --ownership-report")
            owner = validate_ownership_gate(ownership_report, source_before)
            prep, baseline, core, markers = load_numeric_inputs(source_before)
            compile_files, top, rewrites = prepare_numeric(build, output, source_before, artifacts, prep, core)
            result["ownership_gate"] = {"report": project_name(ownership_report.resolve()),
                                        "sha256": sha256_file(ownership_report.resolve()),
                                        "status": owner["status"], "simulation": owner["simulation"]}
            result["baseline_proof"] = {"report": project_name(BASE_NUMERIC), "sha256": BASE_NUMERIC_SHA256,
                                        "status": baseline["status"], "marker_count": len(markers)}
            result["original_preparation"] = {"report": project_name(BASE_PREP), "sha256": BASE_PREP_SHA256,
                                               "testbench_rewrites": rewrites}
            result["core_source_closure"] = {"report": project_name(CORE_PREP),
                                              "sha256": CORE_PREP_SHA256,
                                              "closure_sha256": CORE_CLOSURE_SHA256,
                                              "source_count": 28}

        before = input_map([resolve(name) for name in source_before])
        source_before = before
        result["source_sha256_before"] = before
        result["staged_artifacts"] = dict(sorted(artifacts.items()))
        save_result(report_path, result)

        snapshot = ("v12_own_" if suite == "ownership" else "v12_num_") + run_id.replace(".", "")
        compile_log = run_command("xvlog", [str(xvlog), "-sv", *map(str, compile_files)], build, output, result)
        result["checks"].append({"check": "xvlog_source_closure", "status": "PASS",
                                 "details": {"source_count": len(compile_files),
                                             "source_sha256": [sha256_file(path) for path in compile_files]}})
        save_result(report_path, result)
        elaborate = [str(xelab), "-mt", "2"]
        if suite == "numeric":
            elaborate.extend(["-L", "unimacro_ver", "-L", "unisims_ver"])
        elaborate.extend([top, "-s", snapshot])
        if suite == "numeric":
            elaborate.insert(-2, "glbl")
        run_command("xelab", elaborate, build, output, result)
        sim_log = run_command("xsim", [str(xsim), snapshot, "-runall"], build, output, result)
        if suite == "ownership":
            simulation = marker_values(sim_log, "FEATURE_INPUT_CAPTURE_V12_OWNERSHIP_PASS")
            require(simulation == OWNERSHIP_EXPECTED,
                    f"V12 ownership coverage differs from its exact oracle: {simulation}")
            result.update({"status": "PASS_V12_OWNERSHIP_XSIM_ONLY", "simulation": simulation,
                           "scope": "Two-entry descriptor ownership, bank exclusion, cancel flush/reuse, and byte/mask response checks across both banks only."})
        else:
            marker_lines = baseline["actual_pass_markers"]
            for marker in marker_lines:
                require(sim_log.splitlines().count(marker) == 1,
                        "original-golden numerical marker mismatch: " + marker.split(" ", 1)[0])
            result.update({"status": "PASS_V12_ORIGINAL_GOLDEN_CONV_POOL_NUMERICAL_XSIM_ONLY",
                           "actual_pass_markers": marker_lines,
                           "scope": "Original staged Conv/Pool/retained-Conv numerical proof against frozen golden fixtures; no synthesis, route, fullgraph, board, or FPS acceptance."})
        result["checks"].append({"check": "xsim_marker_oracle", "status": "PASS"})
        require(source_before == {name: sha256_file(resolve(name)) for name in source_before},
                "input source hash changed during XSim")
        require_quiescent()
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        result["failure"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        result["source_sha256_before"] = source_before
        result["source_sha256_after"] = {name: sha256_file(resolve(name)) for name in source_before}
        if result["source_sha256_after"] != result["source_sha256_before"]:
            result["status"] = "FAILED_SOURCE_INTEGRITY"
        result["artifact_sha256"] = {
            project_name(path): sha256_file(path)
            for folder in (output, build)
            for path in folder.rglob("*") if path.is_file() and path != report_path
        }
        result["report_path"] = project_name(report_path)
        result.pop("report_path_obj", None)
        save_result(report_path, result)
    print(json.dumps({"status": result["status"], "suite": suite,
                      "report": project_name(report_path), "build": project_name(build),
                      "errors": result["errors"]}))
    return 0 if result["status"].startswith("PASS_") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("ownership", "numeric"), required=True)
    parser.add_argument("--ownership-report", type=Path,
                        help="exact passing V12 ownership report required for --suite numeric")
    args = parser.parse_args(argv)
    if args.suite == "numeric" and args.ownership_report is None:
        parser.error("--suite numeric requires --ownership-report")
    if args.suite == "ownership" and args.ownership_report is not None:
        parser.error("--ownership-report is only valid for --suite numeric")
    return run_suite(args.suite, args.ownership_report)


if __name__ == "__main__":
    raise SystemExit(main())
