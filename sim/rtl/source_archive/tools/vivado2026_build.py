#!/usr/bin/env python3
"""Run the board-independent Vivado 2026.1 migration checks for Tile64."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
FLOW_TCL = ROOT / "deployment" / "hardware" / "toolchain2026" / "vivado2026_flow.tcl"
RTL_DIR = ROOT / "deployment" / "hardware" / "toolchain2026" / "rtl"
TB_DIR = ROOT / "deployment" / "hardware" / "toolchain2026" / "tests"
DEFAULT_PART = "xc7z100ffg900-2"
VITIS_XSA = ROOT / "validation" / "vivado2026" / "generic_ps_only_xsa" / "system.xsa"
VALIDATION_DIR = ROOT / "validation" / "vivado2026"
TASK_RESULTS_DIR = VALIDATION_DIR / "task_results"
BUILD_REPORT = VALIDATION_DIR / "build_report.json"
TASK_NAMES = (
    "source_snapshot",
    "tool_version",
    "inventory",
    "sim_mac",
    "sim_axis",
    "ooc_mac",
    "ooc_axis",
    "xsa",
    "xsa_validation",
)
CURRENT_COMMANDS: list[dict[str, object]] = []
sys.path.insert(0, str(ROOT / "tools"))
from project_config import load_project_config, resolve_external_path


def resolve_vivado_root(override: Path | None = None) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    _, config, local = load_project_config(ROOT)
    vivado_root = resolve_external_path(config, local, "vivado.target2026.1")
    if vivado_root is None:
        raise FileNotFoundError("Vivado 2026.1 root is not configured; set config/local_paths.json or --vivado-root.")
    return vivado_root


def tool_paths(vivado_root_override: Path | None = None) -> tuple[Path, Path]:
    vivado_root = resolve_vivado_root(vivado_root_override)
    bin_dir = vivado_root / "bin"
    required = [bin_dir / "vivado.bat", bin_dir / "xvlog.bat", bin_dir / "xelab.bat", bin_dir / "xsim.bat"]
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing Vivado 2026.1 tools: " + ", ".join(map(str, missing)))
    return bin_dir, bin_dir / "vivado.bat"


def run_command(command: list[str | Path], cwd: Path, log_path: Path) -> str:
    cwd.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        completed = subprocess.run(
            [str(item) for item in command],
            cwd=cwd,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    output = log_path.read_text(encoding="utf-8", errors="replace")
    CURRENT_COMMANDS.append({
        "command": [str(item) for item in command],
        "cwd": str(cwd.resolve().relative_to(ROOT)),
        "returncode": completed.returncode,
        "accepted": completed.returncode == 0,
        "log": str(log_path.resolve().relative_to(ROOT)),
    })
    print(f"[{log_path.relative_to(ROOT)}] exit={completed.returncode}")
    print_tail(output)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {completed.returncode}; see {log_path}")
    return output


def print_tail(output: str, count: int = 16) -> None:
    for line in output.splitlines()[-count:]:
        print("  " + line)


def run_vivado(task: str, out_dir: Path, extra: tuple[str, ...] = (), vivado_root: Path | None = None) -> str:
    _, vivado = tool_paths(vivado_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "vivado.stdout.log"
    vivado_log = out_dir / "vivado.log"
    command: list[str | Path] = [
        vivado,
        "-mode",
        "batch",
        "-nojournal",
        "-log",
        vivado_log,
        "-source",
        FLOW_TCL,
        "-tclargs",
        task,
        out_dir,
        *extra,
    ]
    output = run_command(command, out_dir, log_path)
    marker = f"VIVADO2026_SUCCESS task={task}"
    if marker not in output:
        raise RuntimeError(f"Vivado did not report task completion marker '{marker}'.")
    return output


def verify_version(vivado_root: Path | None = None) -> None:
    _, vivado = tool_paths(vivado_root)
    log = ROOT / "validation" / "vivado2026" / "tool_version.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    version_work_dir = VALIDATION_DIR / "version_probe"
    version_work_dir.mkdir(parents=True, exist_ok=True)
    vivado_log = version_work_dir / "vivado.log"
    command = [str(vivado), "-log", str(vivado_log), "-version"]
    with log.open("w", encoding="utf-8", errors="replace") as handle:
        completed = subprocess.run(
            command,
            cwd=version_work_dir,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    output = log.read_text(encoding="utf-8", errors="replace")
    CURRENT_COMMANDS.append({
        "command": command,
        "cwd": str(version_work_dir.resolve().relative_to(ROOT)),
        "returncode": completed.returncode,
        "accepted": bool(re.search(r"Vivado v2026\.1\b", output, re.IGNORECASE)) and completed.returncode in (0, 1),
        "acceptance": "2026.1 banner; launcher may return 1 for version-only mode",
        "log": str(log.resolve().relative_to(ROOT)),
        "vivado_log": str(vivado_log.resolve().relative_to(ROOT)),
    })
    if not re.search(r"Vivado v2026\.1\b", output, re.IGNORECASE):
        raise RuntimeError("Installed tool did not identify itself as Vivado 2026.1.")
    if completed.returncode not in (0, 1):
        raise RuntimeError(f"Vivado version probe exited unexpectedly with {completed.returncode}.")
    print(f"[{log.relative_to(ROOT)}] version banner verified (exit={completed.returncode})")
    print_tail(output, count=5)


def simulator_top(top: str, out_dir: Path, vivado_root: Path | None = None) -> str:
    bin_dir, _ = tool_paths(vivado_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    common_mac = [RTL_DIR / "v8_tile64_mac.v"]
    if top == "tb_v8_tile64_mac":
        sources = common_mac + [
            TB_DIR / "reference" / "v8_tile64_mac_reference.v",
            TB_DIR / "tb_v8_tile64_mac.v",
        ]
        required_pass = "PASS v8_tile64_mac full depth, 17/33/63 tails, saturation, and invalid lane check"
    elif top == "tb_v8_tile64_axis":
        sources = common_mac + [
            RTL_DIR / "v8_tile64_axis.v",
            TB_DIR / "tb_v8_tile64_axis.v",
        ]
        required_pass = "PASS v8_tile64_axis ABI, 4096 results, max taps, tails, error/abort recovery, and backpressure"
    else:
        raise ValueError(f"Unsupported simulator testbench: {top}")

    xvlog = bin_dir / "xvlog.bat"
    xelab = bin_dir / "xelab.bat"
    xsim = bin_dir / "xsim.bat"
    run_command([xvlog, "--work", "work", *sources], out_dir, out_dir / "xvlog.log")
    snapshot = f"{top}_2026"
    run_command(
        [xelab, "--mt", "2", "--debug", "typical", f"work.{top}", "--snapshot", snapshot],
        out_dir,
        out_dir / "xelab.log",
    )
    output = run_command([xsim, snapshot, "--R"], out_dir, out_dir / "xsim.log")
    if required_pass not in output or re.search(r"\b(FAIL|FATAL)\b", output, re.IGNORECASE):
        raise RuntimeError(f"Simulation did not produce its expected PASS marker: {top}")
    return required_pass


def parse_device_inventory(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    parts = [line.removeprefix("part=") for line in text.splitlines() if line.startswith("part=")]
    if not parts or any(not re.fullmatch(r"xc7z100[a-z0-9-]+", part, re.IGNORECASE) for part in parts):
        raise ValueError(f"Invalid or empty XC7Z100 part inventory: {path}")
    return parts


def verify_source_snapshot() -> list[dict[str, str]]:
    manifest_path = ROOT / "deployment" / "hardware" / "toolchain2026" / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verified = []
    for entry in manifest.get("sources", []):
        copy_path = ROOT / entry["copy"]
        expected = entry["sha256"].replace(" ", "").lower()
        copy_digest = hashlib.sha256(copy_path.read_bytes()).hexdigest()
        if copy_digest != expected:
            raise ValueError(f"Migration source copy hash mismatch: {copy_path}")
        source = entry["source"]
        # Active candidate RTL and testbench sources are present in this project.
        # The frozen MAC reference is intentionally from the archived legacy tree.
        if source.startswith("deployment/"):
            source_path = ROOT / source
            source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
            if source_digest != expected:
                raise ValueError(f"Migration copy no longer matches its active source: {source_path}")
        verified.append({"source": source, "copy": entry["copy"], "sha256": expected})
    if len(verified) != 5:
        raise ValueError(f"Expected five provenance entries, found {len(verified)}")
    return verified


def validate_xsa(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"Expected XSA is missing: {path}")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        hwh_names = [name for name in names if name.lower().endswith(".hwh")]
        if not hwh_names:
            raise ValueError("XSA does not contain system.hwh metadata for Vitis.")
        hwh = archive.read(hwh_names[0]).decode("utf-8", errors="replace")
        hwh_root = ElementTree.fromstring(hwh)
        ps7_modules = [
            module
            for module in hwh_root.iter("MODULE")
            if module.attrib.get("VLNV") == "xilinx.com:ip:processing_system7:5.5"
            and module.attrib.get("MODTYPE") == "processing_system7"
        ]
        if len(ps7_modules) != 1:
            raise ValueError("XSA HWH must contain exactly one Zynq-7000 processing_system7 IP module.")
        ps7_parameters = {
            parameter.attrib.get("NAME"): parameter.attrib.get("VALUE")
            for parameter in ps7_modules[0].iter("PARAMETER")
        }
        if ps7_parameters.get("PCW_UIPARAM_DDR_ENABLE") != "0":
            raise ValueError("PS-only compatibility XSA must explicitly disable DDR in the PS7 configuration.")
        peripheral_enable_parameters = {
            name: value
            for name, value in ps7_parameters.items()
            if name and re.fullmatch(r"PCW_[A-Z0-9_]*PERIPHERAL_ENABLE", name)
        }
        if not peripheral_enable_parameters or any(value != "0" for value in peripheral_enable_parameters.values()):
            raise ValueError("PS-only compatibility XSA must have every PS7 MIO peripheral disabled.")
        external_ports = hwh_root.find("EXTERNALPORTS")
        external_port_names = [
            port.attrib.get("NAME", "")
            for port in (external_ports.iter("PORT") if external_ports is not None else [])
        ]
        if any("DDR" in name.upper() for name in external_port_names):
            raise ValueError("PS-only compatibility XSA unexpectedly exposes external DDR ports.")
        if any(name.lower().endswith((".bit", ".bin")) for name in names):
            raise ValueError("PS-only compatibility XSA unexpectedly contains a bitstream or binary image.")
        xsa_meta = json.loads(archive.read("xsa.json").decode("utf-8-sig")) if "xsa.json" in names else {}
        part = xsa_meta.get("devices", [{}])[0].get("part", {}).get("name")
        if part != "xc7z020clg400-2":
            raise ValueError(f"PS-only compatibility XSA must remain on the legacy 7020 fixture part; found {part!r}.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": str(path),
        "sha256": digest,
        "hwh": hwh_names[0],
        "classification": "legacy2026_ps_only_compatibility",
        "part": part,
        "processor_identity": "Zynq-7000 Cortex-A9 processing system (PS7)",
        "processor_ip_vlnv": ps7_modules[0].attrib["VLNV"],
        "processor_module_type": ps7_modules[0].attrib["MODTYPE"],
        "processor_ip_type": ps7_modules[0].attrib.get("IPTYPE"),
        "processor_module_instance": ps7_modules[0].attrib.get("INSTANCE"),
        "processor_ip_hardware_version": ps7_modules[0].attrib.get("HWVERSION"),
        "ddr_enable_parameter": f"PCW_UIPARAM_DDR_ENABLE={ps7_parameters['PCW_UIPARAM_DDR_ENABLE']}",
        "ddr_enabled": False,
        "mio_peripheral_enable_parameters": peripheral_enable_parameters,
        "mio_peripherals_enabled": False,
        "external_port_names": external_port_names,
        "bitstream_present": False,
        "vitis_consumed": False,
    }


def verify_artifact_hashes(expected_hashes: dict[str, str], root: Path = ROOT) -> list[dict[str, str | None]]:
    mismatches = []
    for relative_path, expected_hash in expected_hashes.items():
        artifact_path = root / relative_path
        actual_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest() if artifact_path.is_file() else None
        if actual_hash != expected_hash:
            mismatches.append({
                "path": relative_path,
                "expected_sha256": expected_hash,
                "actual_sha256": actual_hash,
            })
    return mismatches


def report_artifact_integrity(task_result: dict[str, object], root: Path = ROOT) -> dict[str, object]:
    recorded_hash_sets = {
        field: task_result.get(field)
        for field in ("artifact_sha256", "post_validation_artifact_sha256")
        if task_result.get(field)
    }
    if not recorded_hash_sets:
        return {"status": "NOT_CAPTURED"}

    mismatches = []
    for hash_set_name, expected_hashes in recorded_hash_sets.items():
        for mismatch in verify_artifact_hashes(expected_hashes, root):
            mismatches.append({"hash_set": hash_set_name, **mismatch})
    if mismatches:
        return {
            "status": "MISMATCH",
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "mismatches": mismatches,
        }
    return {
        "status": "VERIFIED",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "hash_sets_checked": sorted(recorded_hash_sets),
    }


def hash_artifacts(paths: list[Path]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in paths:
        if path.is_file():
            hashes[str(path.resolve().relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def write_build_report(source_hashes: list[dict[str, str]]) -> None:
    refresh_ooc_task_results()
    tasks: dict[str, dict[str, object]] = {}
    for name in TASK_NAMES:
        result_path = TASK_RESULTS_DIR / f"{name}.json"
        if result_path.is_file():
            tasks[name] = json.loads(result_path.read_text(encoding="utf-8"))
            execution_sources = tasks[name].get("execution_source_hashes")
            if execution_sources is None:
                tasks[name]["execution_source_identity_status"] = "NOT_CAPTURED_AT_EXECUTION"
            else:
                current_sources = execution_source_hashes()
                flow_matches = execution_sources.get("vivado_flow_tcl_sha256") == current_sources["vivado_flow_tcl_sha256"]
                manifest_captured = "source_manifest_sha256" in execution_sources
                manifest_matches = (
                    not manifest_captured
                    or execution_sources["source_manifest_sha256"] == current_sources["source_manifest_sha256"]
                )
                wrapper_matches = execution_sources.get("vivado_wrapper_sha256") == current_sources["vivado_wrapper_sha256"]
                if not (flow_matches and manifest_matches):
                    identity_status = "STALE_FLOW_OR_INPUTS"
                elif not manifest_captured and not wrapper_matches:
                    identity_status = "WRAPPER_CHANGED_FLOW_STABLE_MANIFEST_NOT_CAPTURED"
                elif not manifest_captured:
                    identity_status = "MANIFEST_NOT_CAPTURED_AT_EXECUTION"
                elif not wrapper_matches:
                    identity_status = "WRAPPER_CHANGED_FLOW_AND_INPUTS_STABLE"
                else:
                    identity_status = "RECORDED_CURRENT"
                tasks[name]["execution_source_identity_status"] = identity_status
                if tasks[name].get("status") == "PASS" and not (flow_matches and manifest_matches):
                    tasks[name]["recorded_execution_status"] = "PASS"
                    tasks[name]["status"] = "STALE"
            integrity = report_artifact_integrity(tasks[name])
            if integrity["status"] == "MISMATCH" and tasks[name].get("status") == "PASS":
                tasks[name]["recorded_execution_status"] = "PASS"
                tasks[name]["status"] = "ARTIFACT_MISMATCH"
            tasks[name]["report_artifact_integrity"] = integrity
        else:
            tasks[name] = {"status": "NOT_RUN"}
    inventory_path = VALIDATION_DIR / "inventory" / "device_inventory.txt"
    installed_parts = parse_device_inventory(inventory_path) if inventory_path.is_file() else []
    report = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "aggregation": {
            "mode": "snapshot_of_recorded_task_results",
            "task_result_timestamps_are_original_execution_timestamps": True,
            "report_refresh_reruns_vendor_tasks": False,
            "report_refresh_runs_local_source_and_artifact_checks": True,
        },
        "toolchain": {"name": "Vivado", "version": "2026.1", "build": "6511674"},
        "selected_generic_ooc_part": DEFAULT_PART,
        "installed_xc7z100_parts": installed_parts,
        "source_hashes": source_hashes,
        "claims": {
            "route_performed": False,
            "board_build_or_validation_performed": False,
            "fps_measured": False,
            "generic_ooc_reports_are_estimates_only": True,
        },
        "tasks": tasks,
        "current_source_hashes": execution_source_hashes(),
    }
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def execute_stage(
    name: str,
    operation,
    artifact_paths: list[Path],
) -> object:
    global CURRENT_COMMANDS
    CURRENT_COMMANDS = []
    started = datetime.now(timezone.utc).isoformat()
    source_hashes_at_start = execution_source_hashes()
    try:
        summary = operation()
        status = "PASS"
        error = None
    except Exception as exc:
        summary = None
        status = "FAIL"
        error = str(exc)
        finished = datetime.now(timezone.utc).isoformat()
        result = {
            "status": status,
            "started_at_utc": started,
            "finished_at_utc": finished,
            "execution_source_hashes": source_hashes_at_start,
            "execution_source_hashes_unchanged_during_stage": source_hashes_at_start == execution_source_hashes(),
            "commands": CURRENT_COMMANDS,
            "artifact_sha256": hash_artifacts(artifact_paths),
            "error": error,
        }
        TASK_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (TASK_RESULTS_DIR / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        write_build_report(verify_source_snapshot())
        raise
    finished = datetime.now(timezone.utc).isoformat()
    result = {
        "status": status,
        "started_at_utc": started,
        "finished_at_utc": finished,
        "execution_source_hashes": source_hashes_at_start,
        "execution_source_hashes_unchanged_during_stage": source_hashes_at_start == execution_source_hashes(),
        "commands": CURRENT_COMMANDS,
        "artifact_sha256": hash_artifacts(artifact_paths),
        "summary": summary,
    }
    TASK_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (TASK_RESULTS_DIR / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    write_build_report(verify_source_snapshot())
    return summary


def ooc_summary(top: str, out_dir: Path) -> dict[str, object]:
    rpt = out_dir / "utilization.rpt"
    timing = out_dir / "timing_estimate.rpt"
    return {
        "part": DEFAULT_PART,
        "top": top,
        "mode": "out_of_context_synthesis_only",
        "resource_estimate": parse_ooc_utilization(rpt, top),
        "timing_estimate": parse_ooc_timing(timing),
        "resources_report": str(rpt.resolve().relative_to(ROOT)),
        "timing_report": str(timing.resolve().relative_to(ROOT)),
        "route_performed": False,
        "board_validated": False,
        "fps_measured": False,
    }


def refresh_ooc_task_results() -> None:
    for name, top in (("ooc_mac", "v8_tile64_mac"), ("ooc_axis", "v8_tile64_axis")):
        result_path = TASK_RESULTS_DIR / f"{name}.json"
        if not result_path.is_file():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("status") != "PASS":
            continue
        artifact_mismatches = verify_artifact_hashes(result.get("artifact_sha256", {}))
        if artifact_mismatches:
            result["recorded_execution_status"] = "PASS"
            result["status"] = "ARTIFACT_MISMATCH"
            result["artifact_integrity"] = {"status": "MISMATCH", "mismatches": artifact_mismatches}
            result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            continue
        out_dir = VALIDATION_DIR / "ooc" / DEFAULT_PART / top
        result.setdefault("summary", {}).update({
            "resource_estimate": parse_ooc_utilization(out_dir / "utilization.rpt", top),
            "timing_estimate": parse_ooc_timing(out_dir / "timing_estimate.rpt"),
        })
        result["artifact_integrity"] = {"status": "VERIFIED", "checked_at_utc": datetime.now(timezone.utc).isoformat()}
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def execution_source_hashes() -> dict[str, str]:
    manifest_path = ROOT / "deployment" / "hardware" / "toolchain2026" / "source_manifest.json"
    return {
        "vivado_wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "vivado_flow_tcl_sha256": hashlib.sha256(FLOW_TCL.read_bytes()).hexdigest(),
        "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }


def revalidate_existing_xsa() -> dict[str, object]:
    result_path = TASK_RESULTS_DIR / "xsa.json"
    failure_archive = TASK_RESULTS_DIR / "xsa_first_validation_failure.json"
    metadata_path = VITIS_XSA.parent / "xsa_metadata.json"
    validation_started = datetime.now(timezone.utc).isoformat()
    if not result_path.is_file():
        raise FileNotFoundError("No previous XSA export result exists; use --task xsa to generate it first.")
    previous = json.loads(result_path.read_text(encoding="utf-8"))
    if previous.get("status") not in ("FAIL", "PASS"):
        raise ValueError(f"Cannot revalidate an XSA result in status {previous.get('status')!r}.")
    if not failure_archive.exists():
        shutil.copy2(result_path, failure_archive)
    if previous.get("status") == "FAIL" and not failure_archive.is_file():
        raise FileNotFoundError("The initial XSA validation failure could not be preserved.")
    initial_failure = json.loads(failure_archive.read_text(encoding="utf-8"))
    if initial_failure.get("status") != "FAIL":
        raise ValueError("Preserved first XSA validation record is not the original failure.")

    integrity_mismatches = verify_artifact_hashes(previous.get("artifact_sha256", {}))
    if integrity_mismatches:
        raise ValueError("Existing XSA output hashes no longer match the first export record.")
    post_validation_mismatches = verify_artifact_hashes(previous.get("post_validation_artifact_sha256", {}))
    if post_validation_mismatches:
        raise ValueError("Existing post-validation XSA metadata no longer matches its recorded hash.")
    initial_hashes = initial_failure.get("artifact_sha256", {})
    if initial_hashes != previous.get("artifact_sha256", {}):
        raise ValueError("Preserved first XSA failure artifact hashes differ from the export record.")
    metadata = validate_xsa(VITIS_XSA)
    artifact_key = str(VITIS_XSA.resolve().relative_to(ROOT))
    recorded_xsa_hash = previous.get("artifact_sha256", {}).get(artifact_key)
    if not recorded_xsa_hash or metadata["sha256"] != recorded_xsa_hash:
        raise ValueError("Revalidated XSA does not match the immutable first-export hash.")

    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    validation_finished = datetime.now(timezone.utc).isoformat()
    prior_error = initial_failure.get("error")
    previous["status"] = "PASS"
    previous.pop("error", None)
    previous["summary"] = metadata
    previous["artifact_integrity"] = {
        "status": "VERIFIED",
        "checked_at_utc": validation_finished,
        "first_export_hashes_preserved": True,
    }
    previous["post_execution_validation"] = {
        "mode": "offline_existing_xsa_archive_revalidation",
        "started_at_utc": validation_started,
        "finished_at_utc": validation_finished,
        "xsa_sha256_unchanged": metadata["sha256"] == recorded_xsa_hash,
        "first_validation_failure": str(failure_archive.resolve().relative_to(ROOT)),
        "first_validation_error": prior_error,
        "vivado_rerun": False,
        "vitis_consumed": False,
    }
    previous["post_validation_artifact_sha256"] = hash_artifacts([metadata_path])
    identity_path = TASK_RESULTS_DIR / "xsa_export_source_identity.json"
    if not previous.get("execution_source_hashes") and identity_path.is_file():
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        previous["execution_source_hashes"] = identity["execution_source_hashes"]
        previous["execution_source_identity_capture"] = identity["capture_note"]
    result_path.write_text(json.dumps(previous, indent=2) + "\n", encoding="utf-8")
    return {
        "xsa_sha256": metadata["sha256"],
        "first_export_hash_preserved": True,
        "classification": metadata["classification"],
        "ddr_enabled": metadata["ddr_enabled"],
        "mio_peripherals_enabled": metadata["mio_peripherals_enabled"],
        "bitstream_present": metadata["bitstream_present"],
        "vitis_consumed": False,
        "metadata_path": str(metadata_path.resolve().relative_to(ROOT)),
        "first_failure_path": str(failure_archive.resolve().relative_to(ROOT)),
    }


def parse_ooc_utilization(path: Path, top: str) -> dict[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    row = re.search(
        rf"^\|\s*{re.escape(top)}\s*\|\s*\(top\)\s*\|"
        r"\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|"
        r"\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|",
        text,
        re.MULTILINE,
    )
    if not row:
        raise ValueError(f"Could not parse the top-level utilization row for {top}: {path}")
    names = (
        "total_luts",
        "logic_luts",
        "lutrams",
        "srls",
        "ffs",
        "ramb36",
        "ramb18",
        "dsp_blocks",
    )
    return {name: int(value) for name, value in zip(names, row.groups())}


def parse_ooc_timing(path: Path) -> dict[str, float | int | str | bool]:
    text = path.read_text(encoding="utf-8", errors="replace")
    timing_summary = text.split("Design Timing Summary", maxsplit=1)
    if len(timing_summary) != 2:
        raise ValueError(f"Vivado timing summary is missing: {path}")
    summary_row = re.search(
        r"^\s*([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)\s+(\d+)\s+(\d+)",
        timing_summary[1],
        re.MULTILINE,
    )
    period = re.search(r"period=([\d.]+)ns", text)
    if not summary_row or not period:
        raise ValueError(f"Could not parse Vivado timing summary and clock period: {path}")
    return {
        "generic_clock_period_ns": float(period.group(1)),
        "worst_slack_ns": float(summary_row.group(1)),
        "total_negative_slack_ns": float(summary_row.group(2)),
        "failing_endpoints": int(summary_row.group(3)),
        "timing_scope": "synthesis_estimate_only_no_placement_or_routing",
        "board_route_clock_skew_included": False,
        "timing_note": "The OOC clock has no board clock source or route delay model.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("inventory", "sim", "ooc", "xsa", "xsa-validate", "all", "report"), default="all")
    parser.add_argument("--part", choices=(DEFAULT_PART,), default=DEFAULT_PART)
    parser.add_argument("--vivado-root", type=Path, help="override the configured Vivado 2026.1 root")
    args = parser.parse_args(argv)

    try:
        if args.task == "report":
            source_hashes = verify_source_snapshot()
            write_build_report(source_hashes)
            print(f"Build report refreshed: {BUILD_REPORT.relative_to(ROOT)}")
            return 0

        source_hashes = execute_stage("source_snapshot", verify_source_snapshot, [])

        if args.task == "xsa-validate":
            execute_stage(
                "xsa_validation",
                revalidate_existing_xsa,
                [VITIS_XSA, VITIS_XSA.parent / "xsa_metadata.json"],
            )
            validation_result_path = TASK_RESULTS_DIR / "xsa_validation.json"
            validation_result = json.loads(validation_result_path.read_text(encoding="utf-8"))
            validation_result["commands"] = [{
                "command": [sys.executable, str(Path(sys.argv[0]).resolve()), *sys.argv[1:]],
                "cwd": str(Path.cwd().resolve().relative_to(ROOT)),
                "returncode": 0,
                "accepted": True,
                "mode": "offline_existing_xsa_archive_revalidation",
            }]
            validation_result_path.write_text(json.dumps(validation_result, indent=2) + "\n", encoding="utf-8")
            write_build_report(verify_source_snapshot())
            print(f"VIVADO2026_BUILD_SUCCESS task={args.task}")
            return 0

        execute_stage(
            "tool_version",
            lambda: (verify_version(args.vivado_root) or {"version": "2026.1"}),
            [VALIDATION_DIR / "tool_version.log", VALIDATION_DIR / "version_probe" / "vivado.log"],
        )

        parts: list[str] | None = None
        if args.task in ("inventory", "all"):
            out = VALIDATION_DIR / "inventory"

            def inventory_operation():
                run_vivado("inventory", out, vivado_root=args.vivado_root)
                discovered = parse_device_inventory(out / "device_inventory.txt")
                for required in ("xc7z100ffg900-2", "xc7z100ffg1156-2"):
                    if required not in discovered:
                        raise RuntimeError(f"Expected package/grade part was not found: {required}")
                return {"installed_xc7z100_parts": discovered}

            inventory_summary = execute_stage(
                "inventory",
                inventory_operation,
                [out / "device_inventory.txt", out / "vivado.stdout.log"],
            )
            parts = inventory_summary["installed_xc7z100_parts"]

        if args.task in ("sim", "all"):
            for stage, top, subdir in (
                ("sim_mac", "tb_v8_tile64_mac", "mac"),
                ("sim_axis", "tb_v8_tile64_axis", "axis"),
            ):
                out = VALIDATION_DIR / "sim" / subdir
                execute_stage(
                    stage,
                    lambda top=top, out=out: {"pass_marker": simulator_top(top, out, args.vivado_root)},
                    [out / "xvlog.log", out / "xelab.log", out / "xsim.log"],
                )

        if args.task in ("ooc", "all"):
            if parts is None:
                out = VALIDATION_DIR / "inventory"
                if not (out / "device_inventory.txt").is_file():
                    def inventory_operation():
                        run_vivado("inventory", out, vivado_root=args.vivado_root)
                        discovered = parse_device_inventory(out / "device_inventory.txt")
                        for required in ("xc7z100ffg900-2", "xc7z100ffg1156-2"):
                            if required not in discovered:
                                raise RuntimeError(f"Expected package/grade part was not found: {required}")
                        return {"installed_xc7z100_parts": discovered}

                    inventory_summary = execute_stage(
                        "inventory",
                        inventory_operation,
                        [out / "device_inventory.txt", out / "vivado.stdout.log"],
                    )
                    parts = inventory_summary["installed_xc7z100_parts"]
                parts = parse_device_inventory(out / "device_inventory.txt")
            if args.part not in parts:
                raise RuntimeError(f"Selected generic OOC part is not installed: {args.part}")
            for stage, top in (("ooc_mac", "v8_tile64_mac"), ("ooc_axis", "v8_tile64_axis")):
                out = VALIDATION_DIR / "ooc" / args.part / top

                def ooc_operation(top=top, out=out):
                    run_vivado("ooc", out, (args.part, top), args.vivado_root)
                    return ooc_summary(top, out)

                execute_stage(
                    stage,
                    ooc_operation,
                    [out / "synthesis_result.txt", out / "utilization.rpt", out / "timing_estimate.rpt", out / "post_synth.dcp"],
                )

        if args.task in ("xsa", "all"):
            def xsa_operation():
                run_vivado("xsa", VITIS_XSA.parent, vivado_root=args.vivado_root)
                metadata = validate_xsa(VITIS_XSA)
                (VITIS_XSA.parent / "xsa_metadata.json").write_text(
                    json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
                )
                return metadata

            execute_stage(
                "xsa",
                xsa_operation,
                [VITIS_XSA, VITIS_XSA.parent / "xsa_scope.txt", VITIS_XSA.parent / "xsa_metadata.json"],
            )

        write_build_report(verify_source_snapshot())
        print(f"VIVADO2026_BUILD_SUCCESS task={args.task}")
    except (FileNotFoundError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f"VIVADO2026_BUILD_FAILURE: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
