"""Conditional XSim/golden and fresh core route for registered-response-bank V1."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_DIR = ROOT / "deployment/hardware/z100_2026/registered_response_bank_v1"
MANIFEST = CANDIDATE_DIR / "source_manifest_v1.json"
CANDIDATE_RTL = CANDIDATE_DIR / "z100_feature_banks_pingpong_writepipe_v7.sv"
BASE_BANK = ROOT / "build/v12p_d46da432/rtl/z100_feature_banks_pingpong_writepipe_v7.sv"
CHILD_BANK = ROOT / "build/v12p_d46da432/rtl/z100_feature_banks_4read_writepipe_4k_v5.sv"
LEAF_BANK = ROOT / "build/v12p_d46da432/rtl/z100_feature_banks_writepipe_4k_v5.sv"
MITER_TB = CANDIDATE_DIR / "tb_z100_registered_response_bank_miter_v1.sv"
SOURCE_REVIEW = ROOT / "validation/board_z100/response_bank_primary_source_review/20261027T134126.399751Z/result.json"
BOOLEAN_REVIEW = ROOT / "validation/board_z100/response_bank_primary_boolean_review/20261027T133834.407679Z/result.json"
BOOLEAN_CHECKER = ROOT / "tools/check_response_bank_valid_domain_v1.py"
PHASE1_RUN = ROOT / "validation/board_z100/v12_A_default_physopt_route/20261027t212850z_default_physopt"
PHASE1_REPORT = PHASE1_RUN / "result.json"
REVIEWER = ROOT / "tools/review_z100_A_default_physopt_route_v1.py"
VENDOR = Path("C:/appload/2026.1/Vivado/bin")
VIVADO_BAT = VENDOR / "vivado.bat"
XVLOG = VENDOR / "xvlog.bat"
XELAB = VENDOR / "xelab.bat"
XSIM = VENDOR / "xsim.bat"
LOCK_NAME = "Local\\Z100_Vivado_Implementation"
VENDOR_NAMES = {"vivado.exe", "xvlog.exe", "xelab.exe", "xsim.exe", "xsimk.exe", "xvhdl.exe", "xsc.exe"}
PHASE1_PID = 29824
PHASE1_CONTROLLER_PID = 33068
EXPECTED_BASE_BANK = "70719780ff5428755dc562684fedd9c793a9375eeebd93959df11aafb9232662"
EXPECTED_CANDIDATE = "fd90b026c3992b49819ead401e705eda599a8b3528547fba00da34dafbff5c04"
EXPECTED_BOOLEAN_REPORT = "validation/board_z100/response_bank_primary_boolean_review/20261027T133834.407679Z/result.json"
EXPECTED_BOOLEAN_REPORT_SHA = "d7688cf5bdfcef48873f969c25daf8b8e925f9685f1e05cf9223864d5c7668e0"
EXPECTED_BOOLEAN_TOOL_SHA = "f3cae2b8fce1fc0a9d638fdf41a6969f516cb2fa48dc0131675bb84ce1b95574"
EXPECTED_SOURCE_REVIEW_SHA = "e985562dae2a05a8dd4740d7a904f9301a175c1d6493f9174eb65a774369adcd"


class GateError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise GateError(message)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rel(path: Path) -> str:
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        value = path.as_posix()
        require(len(value) > 2 and value[1:3] == ":/", f"external path is not drive-qualified: {value}")
        return "external/" + value[0] + value[2:]


def resolve_binding(value: str | Path) -> Path:
    text = str(value).replace("\\", "/")
    if text.startswith("external/C/"):
        return Path("C:/" + text[len("external/C/"):]).resolve()
    path = Path(text)
    return (path if path.is_absolute() else ROOT / path).resolve()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_inventory() -> list[dict[str, Any]]:
    ps = ("$ErrorActionPreference='Stop'; "
          "@(Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine) "
          "| ConvertTo-Json -Compress")
    completed = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=30, check=True)
    if not completed.stdout.strip():
        return []
    value = json.loads(completed.stdout)
    return value if isinstance(value, list) else ([value] if value else [])


def vendor_inventory() -> list[dict[str, Any]]:
    return [row for row in process_inventory()
            if str(row.get("Name", "")).lower() in VENDOR_NAMES]


def system_resources() -> dict[str, float]:
    ps = ("$os=Get-CimInstance Win32_OperatingSystem; "
          "$d=Get-PSDrive -Name C; "
          "[pscustomobject]@{available_ram_gib=[math]::Round($os.FreePhysicalMemory*1KB/1GB,3); "
          "c_free_gib=[math]::Round($d.Free/1GB,3)} | ConvertTo-Json -Compress")
    completed = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=30, check=True)
    value = json.loads(completed.stdout)
    return {k: float(v) for k, v in value.items()}


class NamedMutex:
    def __init__(self, timeout_ms: int = 0):
        self.timeout_ms = timeout_ms
        self.handle = None

    def __enter__(self):
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel32 = kernel32
        self.handle = kernel32.CreateMutexW(None, False, LOCK_NAME)
        require(bool(self.handle), f"CreateMutexW failed: {ctypes.get_last_error()}")
        result = kernel32.WaitForSingleObject(self.handle, self.timeout_ms)
        if result not in (0, 0x80):
            kernel32.CloseHandle(self.handle)
            self.handle = None
            if result == 0x102:
                raise TimeoutError("vendor serialization mutex is busy")
            raise GateError(f"WaitForSingleObject failed: 0x{result:08x}")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.handle:
            self.kernel32.ReleaseMutex(self.handle)
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


def set_status(path: Path, report: dict[str, Any], status: str, **fields: Any) -> None:
    report.update(status=status, updated_at_utc=now(), **fields)
    atomic_json(path, report)


def load_v12_helper():
    path = ROOT / "tools/validate_z100_feature_input_capture_v12.py"
    spec = importlib.util.spec_from_file_location("z100_v12_original_golden_helper", path)
    require(spec is not None and spec.loader is not None, "cannot import V12 golden helper")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def candidate_evidence_bindings() -> dict[str, str]:
    manifest = load_json(MANIFEST)
    require(len(manifest.get("sources", [])) == 28, "frozen source manifest must contain 28 files")
    require(sha(BASE_BANK) == EXPECTED_BASE_BANK, "frozen source-bank hash changed")
    require(sha(CANDIDATE_RTL) == EXPECTED_CANDIDATE, "candidate source hash changed")
    source_review = load_json(SOURCE_REVIEW)
    require(sha(SOURCE_REVIEW) == EXPECTED_SOURCE_REVIEW_SHA and
            source_review.get("status") == "PASS_EXACT_SINGLE_EXPRESSION_CHANGE_ONLY" and
            source_review.get("base_sha256") == EXPECTED_BASE_BANK and
            source_review.get("candidate_sha256") == EXPECTED_CANDIDATE and
            source_review.get("rtl_miter_passed") is False and
            source_review.get("fullcore_numeric_passed") is False,
            "primary source review no longer matches the pre-simulation candidate state")
    boolean_report = load_json(BOOLEAN_REVIEW)
    require(boolean_report.get("status") == "PASS_BOUNDED_BOOLEAN_VALID_DOMAIN_ONLY" and
            boolean_report.get("cases") == 256 and boolean_report.get("valid_cases") == 32 and
            boolean_report.get("invalid_selection_differences") == 64 and
            boolean_report.get("source_sha256") == EXPECTED_BASE_BANK and
            sha(BOOLEAN_CHECKER) == EXPECTED_BOOLEAN_TOOL_SHA,
            "primary boolean review/checker mismatch")
    if EXPECTED_BOOLEAN_REPORT_SHA:
        require(sha(BOOLEAN_REVIEW) == EXPECTED_BOOLEAN_REPORT_SHA,
                "primary boolean report SHA changed")
    result = {
        rel(BASE_BANK): sha(BASE_BANK), rel(CANDIDATE_RTL): sha(CANDIDATE_RTL),
        rel(MITER_TB): sha(MITER_TB), rel(SOURCE_REVIEW): sha(SOURCE_REVIEW),
        rel(BOOLEAN_REVIEW): sha(BOOLEAN_REVIEW), rel(BOOLEAN_CHECKER): sha(BOOLEAN_CHECKER),
        rel(MANIFEST): sha(MANIFEST),
    }
    for row in manifest["sources"]:
        source = ROOT / row["path"]
        require(source.is_file() and sha(source) == row["sha256"],
                f"frozen source manifest drift: {row['path']}")
        result[rel(source)] = row["sha256"]
    return result


def run_tool(label: str, argv: list[str], cwd: Path, log: Path,
             state_path: Path, report: dict[str, Any]) -> str:
    active = vendor_inventory()
    require(not active, f"vendor became active before {label}: {active}")
    started = now()
    env = dict(os.environ, XILINX_LOCAL_USER_DATA="no", OMP_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    with log.open("wb") as stream:
        proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=stream,
                                stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        entry = {"label": label, "argv": argv, "cwd": rel(cwd), "pid": proc.pid,
                 "started_at_utc": started, "log": rel(log), "status": "RUNNING"}
        report.setdefault("commands", []).append(entry)
        set_status(state_path, report, label.upper() + "_RUNNING", current_command=entry)
        last_heartbeat = time.monotonic()
        while proc.poll() is None:
            time.sleep(1)
            if time.monotonic() - last_heartbeat >= 15:
                entry["heartbeat_utc"] = now()
                set_status(state_path, report, label.upper() + "_RUNNING", current_command=entry)
                last_heartbeat = time.monotonic()
        entry["return_code"] = proc.returncode
        entry["ended_at_utc"] = now()
        entry["status"] = "COMPLETED" if proc.returncode == 0 else "FAILED"
    text = log.read_text(encoding="utf-8", errors="replace")
    entry["log_sha256"] = sha(log)
    set_status(state_path, report, label.upper() + ("_COMPLETED" if proc.returncode == 0 else "_FAILED"),
               current_command=entry)
    require(proc.returncode == 0, f"{label} returned {proc.returncode}; see {log}")
    require(not re.search(r"(?im)^\s*(?:ERROR:|FATAL:|Fatal:)", text),
            f"{label} emitted a fatal diagnostic; see {log}")
    require(not vendor_inventory(), f"vendor process survived {label}")
    return text


def stage_miter(build_dir: Path, inputs: dict[str, str], staged: dict[str, str]) -> tuple[list[Path], str]:
    unit = build_dir / "miter"
    rtl = unit / "rtl"
    rtl.mkdir(parents=True, exist_ok=False)
    bind = lambda p: inputs.__setitem__(rel(p), sha(p))
    for path in (BASE_BANK, CANDIDATE_RTL, CHILD_BANK, LEAF_BANK, MITER_TB):
        bind(path)
    base_text = BASE_BANK.read_text(encoding="utf-8")
    old_decl = "module z100_feature_banks_pingpong_writepipe_v7 ("
    new_decl = "module z100_feature_banks_pingpong_writepipe_v7_baseline ("
    require(base_text.count(old_decl) == 1, "baseline module rename point is not unique")
    old_text = base_text.replace(old_decl, new_decl, 1)
    old_target = rtl / "z100_feature_banks_pingpong_writepipe_v7_baseline.sv"
    old_target.write_text(old_text, encoding="utf-8", newline="\n")
    require(old_target.read_text(encoding="utf-8") == old_text,
            "baseline module rename staging failed")
    staged[rel(old_target)] = sha(old_target)
    child_target = rtl / CHILD_BANK.name
    shutil.copyfile(CHILD_BANK, child_target)
    leaf_target = rtl / LEAF_BANK.name
    shutil.copyfile(LEAF_BANK, leaf_target)
    candidate_target = rtl / CANDIDATE_RTL.name
    shutil.copyfile(CANDIDATE_RTL, candidate_target)
    tb_target = rtl / MITER_TB.name
    shutil.copyfile(MITER_TB, tb_target)
    for path in (child_target, leaf_target, candidate_target, tb_target):
        require(sha(path) == sha({CHILD_BANK.name: CHILD_BANK,
                                 LEAF_BANK.name: LEAF_BANK,
                                 CANDIDATE_RTL.name: CANDIDATE_RTL,
                                 MITER_TB.name: MITER_TB}[path.name]),
                f"miter source staging mismatch: {path.name}")
        staged[rel(path)] = sha(path)
    sources = [leaf_target, child_target, old_target, candidate_target, tb_target]
    return sources, "tb_z100_registered_response_bank_miter_v1"


def run_validation(run_dir: Path) -> int:
    run_dir = run_dir.resolve()
    gate_root = (ROOT / "validation/board_z100/registered_response_bank_v1").resolve()
    require(run_dir.is_relative_to(gate_root), "validation output escaped isolated evidence root")
    build_dir = (ROOT / "build/registered_response_bank_v1" / run_dir.name).resolve()
    state_path = run_dir / "validation_result.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema": "z100-registered-response-bank-validation/1",
        "run_id": run_dir.name, "created_at_utc": now(),
        "status": "PREPARING", "board_access": False,
        "synthesis_or_route_accepted": False, "fullgraph_execution_accepted": False,
        "full_pipeline_30fps_accepted": False, "commands": [], "checks": [],
        "source_before": {}, "staged_artifacts": {}, "errors": [],
    }
    atomic_json(state_path, report)
    try:
        report["source_before"].update(candidate_evidence_bindings())
        resources = system_resources()
        if resources["available_ram_gib"] < 8.0 or resources["c_free_gib"] < 20.0:
            set_status(state_path, report, "DEFERRED_RESOURCES_BELOW_GATE", resources=resources)
            return 75
        active = vendor_inventory()
        if active:
            set_status(state_path, report, "DEFERRED_VENDOR_BUSY", resources=resources,
                       active_vendor_processes=active)
            return 75
        try:
            mutex = NamedMutex(timeout_ms=0)
            mutex.__enter__()
        except TimeoutError:
            set_status(state_path, report, "DEFERRED_MUTEX_BUSY", resources=resources)
            return 75
        try:
            active = vendor_inventory()
            if active:
                set_status(state_path, report, "DEFERRED_VENDOR_BUSY_AFTER_LOCK",
                           resources=resources, active_vendor_processes=active)
                return 75

            v12 = load_v12_helper()
            xvlog, xelab, xsim = (VENDOR / "xvlog.bat", VENDOR / "xelab.bat", VENDOR / "xsim.bat")
            require(all(p.is_file() for p in (xvlog, xelab, xsim)), "Vivado 2026.1 XSim tool missing")
            for p in (v12.__file__, xvlog, xelab, xsim):
                report["source_before"][rel(Path(p))] = sha(Path(p))

            miter_dir = run_dir / "miter"
            miter_build = build_dir / "miter"
            miter_dir.mkdir(exist_ok=False)
            miter_build.mkdir(exist_ok=False)
            source_inputs = dict(report["source_before"])
            staged = {}
            miter_sources, miter_top = stage_miter(miter_build, source_inputs, staged)
            report["source_before"] = source_inputs
            report["staged_artifacts"].update(staged)
            xvlog_log = miter_dir / "xvlog.log"
            run_tool("miter_xvlog", [str(xvlog), "-sv", *map(str, miter_sources)],
                     miter_build, xvlog_log, state_path, report)
            snapshot = "z100_response_bank_miter_v1"
            run_tool("miter_xelab", [str(xelab), "-mt", "2", miter_top, "-s", snapshot],
                     miter_build, miter_dir / "xelab.log", state_path, report)
            miter_log = run_tool("miter_xsim", [str(xsim), snapshot, "-runall"],
                                 miter_build, miter_dir / "xsim.log", state_path, report)
            marker = "REGISTERED_RESPONSE_BANK_MITER_PASS"
            lines = [line for line in miter_log.splitlines() if line.startswith(marker + " ")]
            require(len(lines) == 1, "missing or repeated directed miter pass marker")
            counts = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", lines[0])}
            require(counts.get("accepted_reads") == 7 and counts.get("retired_reads") == 5 and
                    counts.get("held_valid_cycles", 0) > 0,
                    f"directed miter coverage counters unexpected: {counts}")
            report["checks"].append({"check": "old_new_bank_miter_valid_domain_and_byte_oracle",
                                     "status": "PASS", "counts": counts,
                                     "payload_compared_only_when_valid": True,
                                     "covers_other_bank_reload_while_pending": True,
                                     "covers_same_bank_overlap_reset_cancel_and_bad_epoch": True})

            report["status"] = "STAGING_ORIGINAL_V12_NUMERIC_GOLDEN"
            atomic_json(state_path, report)
            prep, baseline, core, markers = v12.load_numeric_inputs(report["source_before"])
            numeric_dir = run_dir / "numeric"
            numeric_build = build_dir / "numeric"
            numeric_dir.mkdir(exist_ok=False)
            numeric_build.mkdir(exist_ok=False)
            artifacts: dict[str, str] = {}
            compile_files, top, rewrites = v12.prepare_numeric(
                numeric_build, numeric_dir, report["source_before"], artifacts, prep, core)
            bank_targets = [p for p in compile_files if p.name == CANDIDATE_RTL.name]
            require(len(bank_targets) == 1, "original V12 golden compile lacks unique bank module")
            bank_target = bank_targets[0]
            require(sha(bank_target) == EXPECTED_BASE_BANK,
                    "numeric staging bank is not the original frozen A RTL")
            shutil.copyfile(CANDIDATE_RTL, bank_target)
            require(sha(bank_target) == EXPECTED_CANDIDATE,
                    "candidate did not replace exactly the staged bank module")
            artifacts[rel(bank_target)] = sha(bank_target)
            manifest = load_json(MANIFEST)
            v12_aliases = {
                "z100_feature_window20_address_shared_v10.sv": v12.ADAPTER_V12.name,
                "z100_native_row20_shared_pool_address_shared_v10.sv": v12.TOP_V12.name,
            }
            numeric_pairs = []
            for row in manifest["sources"]:
                staged_name = (CANDIDATE_RTL.name if row["name"] == CANDIDATE_RTL.name
                               else v12_aliases.get(row["name"], row["name"]))
                staged_path = numeric_build / "rtl" / staged_name
                expected_hash = (EXPECTED_CANDIDATE if row["name"] == CANDIDATE_RTL.name
                                 else row["sha256"])
                require(staged_path.is_file() and sha(staged_path) == expected_hash,
                        f"original-golden staged source differs from frozen A closure: {row['name']} -> {staged_name}")
                numeric_pairs.append({"frozen_source": row["path"], "staged_name": staged_name,
                                      "expected_sha256": expected_hash,
                                      "actual_sha256": sha(staged_path)})
            report["staged_artifacts"].update(artifacts)
            report["numeric_baseline"] = {
                "report": v12.project_name(v12.BASE_NUMERIC),
                "sha256": v12.BASE_NUMERIC_SHA256,
                "status": baseline["status"],
                "expected_exact_markers": markers,
                "testbench_rewrites": rewrites,
                "closure_source_count": 28,
                "staged_source_pairs": numeric_pairs,
                "candidate_override": {"path": rel(CANDIDATE_RTL), "sha256": EXPECTED_CANDIDATE},
                "staged_bank_previous_sha256": EXPECTED_BASE_BANK,
            }
            atomic_json(state_path, report)
            compile_log = run_tool("numeric_xvlog", [str(xvlog), "-sv", *map(str, compile_files)],
                                   numeric_build, numeric_dir / "xvlog.log", state_path, report)
            require("ERROR:" not in compile_log, "original V12 numeric compile error")
            elaborate = [str(xelab), "-mt", "2", "-L", "unimacro_ver", "-L", "unisims_ver",
                         "glbl", top, "-s", "z100_response_bank_original_v12_golden_v1"]
            run_tool("numeric_xelab", elaborate, numeric_build, numeric_dir / "xelab.log",
                     state_path, report)
            numeric_log = run_tool("numeric_xsim",
                                   [str(xsim), "z100_response_bank_original_v12_golden_v1", "-runall"],
                                   numeric_build, numeric_dir / "xsim.log", state_path, report)
            for marker_line in markers:
                require(numeric_log.splitlines().count(marker_line) == 1,
                        "original V12 numerical golden marker mismatch: " + marker_line.split(" ", 1)[0])
            report["checks"].append({"check": "strict_original_v12_conv_pool_retained_conv_goldens",
                                     "status": "PASS", "exact_marker_count": len(markers),
                                     "no_count_whitelist_or_changed_marker": True})

            source_after = {name: sha(v12.resolve(name)) for name in report["source_before"]}
            require(source_after == report["source_before"], "source integrity changed during validation")
            artifact_map = {}
            for folder in (run_dir / "miter", run_dir / "numeric", build_dir):
                for path in folder.rglob("*"):
                    if path.is_file() and path != state_path:
                        artifact_map[rel(path)] = sha(path)
            report["source_after"] = source_after
            report["artifact_sha256"] = dict(sorted(artifact_map.items()))
            report["status"] = "PASS_RESPONSE_BANK_MITER_AND_ORIGINAL_V12_GOLDEN_XSIM_ONLY"
            report["scope"] = "Standalone dual-bank RTL miter plus the frozen V12 numerical golden regression; no synthesis/route/platform/board/FPS acceptance."
            atomic_json(state_path, report)
            return 0
        finally:
            mutex.__exit__(None, None, None)
    except Exception as exc:
        report.setdefault("errors", []).append(f"{type(exc).__name__}: {exc}")
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        report["status"] = "FAILED_CLOSED"
        report["updated_at_utc"] = now()
        atomic_json(state_path, report)
        return 1


def tcl_path(path: Path) -> str:
    value = Path(path).resolve().as_posix()
    require("{" not in value and "}" not in value, f"unescaped Tcl path: {value}")
    return "{" + value + "}"


def create_route_tcl(src_dir: Path, out_dir: Path, manifest: dict[str, Any]) -> Path:
    rtl = [src_dir / row["name"] for row in manifest["sources"]]
    require(len(rtl) == 28 and all(p.is_file() for p in rtl), "fresh 28-source route input is incomplete")
    part = manifest["part"]
    top = manifest["top"]
    p = out_dir / "registered_response_bank_route_v1.tcl"
    lines = [
        "set_param general.maxThreads 2",
        'if {![string match 2026.1* [version -short]]} {error "Requires Vivado 2026.1"}',
        f"read_verilog -sv {' '.join(tcl_path(x) for x in rtl)}",
        f"synth_design -top {top} -part {part} -mode out_of_context -flatten_hierarchy none",
        "create_clock -name row_clk -period 10 [get_ports clk]",
        "opt_design",
        "proc z100_identity {stage threads} {",
        "  set part_name [string map {- {}} [string tolower [get_property PART [current_design]]]]",
        "  if {![string match *xc7z100ffg900-2* [get_property PART [current_design]]] && ![string match *xc7z100ffg9002* $part_name]} {error \"unexpected target part\"}",
        "  set clocks [get_clocks -quiet]",
        "  if {[llength $clocks] != 1 || [get_property NAME [lindex $clocks 0]] ne \"row_clk\" || [get_property PERIOD [lindex $clocks 0]] != 10.0} {error \"row_clk must remain 10ns\"}",
        "  set dsp [llength [get_cells -quiet -hier -filter {REF_NAME == DSP48E1}]]",
        "  set pblocks [llength [get_pblocks -quiet]]",
        "  set blackboxes [llength [get_cells -quiet -hier -filter {IS_BLACKBOX == 1}]]",
        "  if {$dsp != 2016 || $pblocks != 0 || $blackboxes != 0} {error \"resource/constraint identity gate failed\"}",
        "  puts \"Z100_RESPONSE_BANK_IDENTITY stage=$stage part=[get_property PART [current_design]] dsp=$dsp period_ns=10 pblocks=$pblocks threads=$threads\"",
        "}",
        "proc z100_reports {stage out_dir} {",
        "  report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out_dir timing_${stage}.rpt]",
        "  report_utilization -file [file join $out_dir utilization_${stage}.rpt]",
        "  report_design_analysis -congestion -file [file join $out_dir congestion_${stage}.rpt]",
        "}",
        "write_checkpoint -force [file join " + tcl_path(out_dir) + " post_synth.dcp]",
        "z100_identity synth_opt 2",
        "set_param general.maxThreads 8",
        "place_design -directive Default",
        "write_checkpoint -force [file join " + tcl_path(out_dir) + " post_place.dcp]",
        "z100_identity placed 8",
        "z100_reports placed " + tcl_path(out_dir),
        "phys_opt_design",
        "write_checkpoint -force [file join " + tcl_path(out_dir) + " post_default_physopt.dcp]",
        "z100_identity default_physopt 8",
        "z100_reports default_physopt " + tcl_path(out_dir),
        "phys_opt_design -hold_fix",
        "write_checkpoint -force [file join " + tcl_path(out_dir) + " post_hold_fix.dcp]",
        "z100_identity hold_fix 8",
        "z100_reports hold_fix " + tcl_path(out_dir),
        "route_design -directive Default",
        "write_checkpoint -force [file join " + tcl_path(out_dir) + " post_route.dcp]",
        "z100_identity routed 8",
        "report_route_status -file [file join " + tcl_path(out_dir) + " route_status.rpt]",
        "report_timing_summary -delay_type min_max -report_unconstrained -file [file join " + tcl_path(out_dir) + " timing_routed.rpt]",
        "report_timing -delay_type max -max_paths 50 -path_type full_clock_expanded -file [file join " + tcl_path(out_dir) + " setup_paths_routed.rpt]",
        "report_timing -delay_type min -max_paths 50 -path_type full_clock_expanded -file [file join " + tcl_path(out_dir) + " hold_paths_routed.rpt]",
        "report_pulse_width -file [file join " + tcl_path(out_dir) + " pulse_width_routed.rpt]",
        "report_utilization -file [file join " + tcl_path(out_dir) + " utilization_routed.rpt]",
        "report_design_analysis -congestion -file [file join " + tcl_path(out_dir) + " congestion_routed.rpt]",
        "report_drc -file [file join " + tcl_path(out_dir) + " drc_routed.rpt]",
        "set timing_checks [check_timing -verbose -return_string]",
        "set f [open [file join " + tcl_path(out_dir) + " check_timing_routed.rpt] w]",
        "puts $f $timing_checks",
        "close $f",
        'puts "Z100_RESPONSE_BANK_ROUTE_COMPLETE version=[version -short] part=[get_property PART [current_design]] dsp=2016 row_clk_period_ns=10 threads=8"',
        "exit",
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def run_route(run_dir: Path, review_path: Path) -> int:
    run_dir = run_dir.resolve()
    gate_root = (ROOT / "validation/board_z100/registered_response_bank_v1").resolve()
    require(run_dir.is_relative_to(gate_root), "route evidence escaped isolated directory")
    result_path = run_dir / "implementation_result.json"
    report: dict[str, Any] = {"schema": "z100-registered-response-bank-implementation/1",
                              "run_id": run_dir.name, "created_at_utc": now(),
                              "status": "PREPARING", "commands": [], "errors": [],
                              "board_access": False, "full_platform_timing_accepted": False,
                              "full_pipeline_30fps_accepted": False}
    atomic_json(result_path, report)
    try:
        require(sha(BASE_BANK) == EXPECTED_BASE_BANK and sha(CANDIDATE_RTL) == EXPECTED_CANDIDATE,
                "frozen/candidate bank source identity changed")
        stage1 = load_json(PHASE1_REPORT)
        review = load_json(review_path)
        validation = load_json(run_dir / "validation_result.json")
        require(review.get("status") == "LEGAL_ROUTE_SETUP_TIMING_FAILED" and
                review.get("route", {}).get("routable_nets", 0) ==
                review.get("route", {}).get("fully_routed_nets", -1) and
                review.get("route", {}).get("routing_error_nets") == 0 and
                review.get("timing", {}).get("internal_timing_passed") is False and
                review.get("timing", {}).get("setup_failing_endpoints", 0) > 0 and
                review.get("timing", {}).get("hold_failing_endpoints") == 0 and
                review.get("timing", {}).get("pulse_width_failing_endpoints") == 0,
                "phase-1 review is not a legal setup-failing/hold-clean route")
        require(stage1.get("status") == "COMPLETED_REPORTS_READY_PENDING_INDEPENDENT_REVIEW" and
                stage1.get("source_rtl_changed") is False and stage1.get("clock_changed") is False,
                "phase-1 producer final identity/status changed")
        require(validation.get("status") == "PASS_RESPONSE_BANK_MITER_AND_ORIGINAL_V12_GOLDEN_XSIM_ONLY",
                "required real XSim miter/original golden gate not passed")
        require(validation.get("source_before") == validation.get("source_after") and
                validation.get("artifact_sha256"),
                "validation source integrity or artifact hashes are missing")
        for name, digest in validation["source_after"].items():
            path = resolve_binding(name)
            require(path.is_file() and sha(path) == digest,
                    f"validation source binding changed before route: {name}")
        for name, digest in validation["artifact_sha256"].items():
            path = resolve_binding(name)
            require(path.is_file() and sha(path) == digest,
                    f"validation artifact changed before route: {name}")
        manifest = load_json(MANIFEST)
        require(len(manifest.get("sources", [])) == 28 and manifest.get("part") == "xc7z100ffg900-2" and
                manifest.get("clock") == {"name": "row_clk", "period_ns": 10.0} and
                manifest.get("implementation_threads") == 8,
                "frozen route manifest identity changed")
        numeric_pairs = validation.get("numeric_baseline", {}).get("staged_source_pairs", [])
        require(len(numeric_pairs) == 28 and
                all(row.get("actual_sha256") == row.get("expected_sha256") for row in numeric_pairs),
                "original V12 golden simulation is not bound to the matching 28-source closure")
        require(validation.get("commands") and
                any(c.get("label") == "miter_xsim" and c.get("return_code") == 0
                    for c in validation["commands"]) and
                any(c.get("label") == "numeric_xsim" and c.get("return_code") == 0
                    for c in validation["commands"]),
                "miter/golden command completion evidence missing")
        input_bindings = candidate_evidence_bindings()
        input_bindings[rel(review_path)] = sha(review_path)
        input_bindings[rel(PHASE1_REPORT)] = sha(PHASE1_REPORT)
        input_bindings[rel(run_dir / "validation_result.json")] = sha(run_dir / "validation_result.json")
        input_bindings[rel(MANIFEST)] = sha(MANIFEST)
        report["bindings"] = input_bindings
        report["phase1_timing"] = review.get("timing")
        report["phase1_route"] = review.get("route")
        report["validation_result"] = rel(run_dir / "validation_result.json")
        report["source_manifest_sha256"] = sha(MANIFEST)
        report["preflight"] = system_resources()
        active = vendor_inventory()
        if active:
            set_status(result_path, report, "DEFERRED_VENDOR_BUSY", active_vendor_processes=active)
            return 75
        if report["preflight"]["available_ram_gib"] < 8.0 or report["preflight"]["c_free_gib"] < 20.0:
            set_status(result_path, report, "DEFERRED_RESOURCES_BELOW_GATE")
            return 75
        try:
            mutex = NamedMutex(timeout_ms=0)
            mutex.__enter__()
        except TimeoutError:
            set_status(result_path, report, "DEFERRED_MUTEX_BUSY")
            return 75
        try:
            active = vendor_inventory()
            report["preflight"]["vendor_inventory_after_lock"] = active
            require(not active, f"vendor became active after serialization lock: {active}")
            v12 = load_v12_helper()
            v12.require_quiescent()
            build_dir = (ROOT / "build/registered_response_bank_v1" / run_dir.name / "implementation").resolve()
            src_dir = build_dir / "rtl"
            out_dir = run_dir / "implementation"
            require(not build_dir.exists() and not out_dir.exists(), "implementation output path already exists")
            build_dir.mkdir(parents=True, exist_ok=False)
            src_dir.mkdir(parents=True, exist_ok=False)
            out_dir.mkdir(parents=True, exist_ok=False)
            staged = []
            for row in manifest["sources"]:
                src = ROOT / row["path"]
                require(src.is_file() and sha(src) == row["sha256"],
                        f"frozen source drift: {row['path']}")
                dest = src_dir / row["name"]
                if row["name"] == CANDIDATE_RTL.name:
                    shutil.copyfile(CANDIDATE_RTL, dest)
                    require(sha(dest) == EXPECTED_CANDIDATE, "candidate bank RTL staging mismatch")
                    staged.append({"path": rel(dest), "sha256": sha(dest),
                                   "replaces": row["path"], "baseline_sha256": row["sha256"]})
                else:
                    shutil.copyfile(src, dest)
                    require(sha(dest) == row["sha256"], f"source staging mismatch: {row['name']}")
                    staged.append({"path": rel(dest), "sha256": sha(dest), "replaces": row["path"]})
            require(len(staged) == 28 and sum(1 for x in staged if "baseline_sha256" in x) == 1,
                    "fresh source closure must contain exactly one RTL override")
            tcl = create_route_tcl(src_dir, out_dir, manifest)
            vivado_command = [str(VIVADO_BAT), "-mode", "batch", "-nolog", "-nojournal", "-source", str(tcl)]
            report.update({"part": manifest["part"], "clock_period_ns": 10.0,
                           "synthesis_threads": 2, "implementation_threads": 8,
                           "fresh_synthesis": True, "input_checkpoint_reused": False,
                           "pblock_count_expected": 0, "dsp_count_expected": 2016,
                           "staged_source_closure": staged, "tcl": rel(tcl),
                           "tcl_sha256": sha(tcl), "vivado_command": vivado_command,
                           "build_dir": rel(build_dir), "implementation_dir": rel(out_dir)})
            atomic_json(result_path, report)
            require(vivado_command[0] and Path(vivado_command[0]).is_file(), "Vivado 2026.1 launcher missing")
            active = vendor_inventory()
            require(not active, f"vendor became active at launch gate: {active}")
            with (out_dir / "vivado.log").open("wb") as log:
                env = dict(os.environ, XILINX_LOCAL_USER_DATA="no", OMP_NUM_THREADS="1",
                           OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
                proc = subprocess.Popen(vivado_command, cwd=str(out_dir), env=env,
                                        stdout=log, stderr=subprocess.STDOUT,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                report["launcher_pid"] = proc.pid
                report["started_at_utc"] = now()
                report["vendor_processes_at_launch"] = active
                report["vivado_process_pids"] = []
                report["status"] = "RUNNING_FRESH_28_SOURCE_SYNTH_PLACE_PHYSOPT_ROUTE"
                report["commands"] = [{"argv": vivado_command, "launcher_pid": proc.pid,
                                       "started_at_utc": report["started_at_utc"], "status": "RUNNING"}]
                atomic_json(result_path, report)
                heartbeat = time.monotonic()
                while proc.poll() is None:
                    time.sleep(2)
                    current = [row for row in vendor_inventory()
                               if str(row.get("Name", "")).lower() == "vivado.exe"]
                    report["vivado_process_pids"] = [row.get("ProcessId") for row in current]
                    if time.monotonic() - heartbeat >= 15:
                        report["last_heartbeat_utc"] = now()
                        atomic_json(result_path, report)
                        heartbeat = time.monotonic()
                report["commands"][0]["return_code"] = proc.returncode
                report["commands"][0]["ended_at_utc"] = now()
                report["commands"][0]["status"] = "COMPLETED" if proc.returncode == 0 else "FAILED"
                report["vivado_log_sha256"] = sha(out_dir / "vivado.log")
                log_text = (out_dir / "vivado.log").read_text(encoding="utf-8", errors="replace")
                report["vivado_completion_marker"] = "Z100_RESPONSE_BANK_ROUTE_COMPLETE" in log_text
                require(proc.returncode == 0 and report["vivado_completion_marker"] and
                        not re.search(r"(?m)^ERROR:", log_text),
                        "Vivado did not finish cleanly; preserve logs/checkpoints and review")
            report["artifact_sha256"] = {
                rel(p): sha(p) for p in out_dir.rglob("*") if p.is_file()
            }
            report["status"] = "COMPLETED_REPORTS_READY_PENDING_INDEPENDENT_REVIEW"
            report["scope"] = "Fresh OOC 28-source candidate core only; no platform, board, accuracy, or FPS acceptance."
            atomic_json(result_path, report)
            return 0
        finally:
            mutex.__exit__(None, None, None)
    except Exception as exc:
        report.setdefault("errors", []).append(f"{type(exc).__name__}: {exc}")
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        report["status"] = "FAILED_CLOSED"
        report["updated_at_utc"] = now()
        atomic_json(result_path, report)
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)
    val = sub.add_parser("validate")
    val.add_argument("--run-dir", type=Path, required=True)
    route = sub.add_parser("route")
    route.add_argument("--run-dir", type=Path, required=True)
    route.add_argument("--phase1-review", type=Path, required=True)
    args = ap.parse_args()
    if args.mode == "validate":
        return run_validation(args.run_dir)
    return run_route(args.run_dir, args.phase1_review.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
