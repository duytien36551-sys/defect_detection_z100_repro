#!/usr/bin/env python3
"""Verify and rebuild Z100 hardware from the packaged RTL and block design."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

sys.dont_write_bytecode = True

from rebuild_hardware_runtime import SharedMutex, process_inventory, resource_status


BUILD_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BUILD_DIR.parent
BUNDLE = BUILD_DIR / "hardware_source"
UPSTREAM_MANIFEST = "provenance/upstream_manifest.json"
SOURCE_ROOT = "rtl"
DEFAULT_PREPARE_DIR = (
    PROJECT_ROOT.parent
    / ".codex"
    / "engineering_package_repro_20261103"
    / "hardware_prepare_check"
)
DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT.parent
    / ".codex"
    / "engineering_package_repro_20261103"
    / "hardware"
)
PACKAGE_SCHEMA = "z100_hardware_source_package_v2"
ABSOLUTE_PATH_RE = re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/]")
WINDOWS_MAX_PATH = 260
RUN_ID_SAMPLE = "run-20000101T000000.000000Z"
LONGEST_BD_XCI_RELATIVE_PATH = Path(
    "place/project/platform.srcs/sources_1/bd/system/ip/"
    "system_native_conv_backend_local_control_0_0/"
    "system_native_conv_backend_local_control_0_0.xci"
)
WINDOWS_PATH_PREFLIGHT = {
    "max_path_including_terminator": WINDOWS_MAX_PATH,
    "run_id_sample": RUN_ID_SAMPLE,
    "longest_generated_path_from_run_directory": LONGEST_BD_XCI_RELATIVE_PATH.as_posix(),
    "preserve_subst_drive_alias_for_writes": True,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_windows_max_path(path: Path, description: str) -> None:
    path_text = os.fspath(path)
    if len(path_text) >= WINDOWS_MAX_PATH:
        raise ValueError(
            f"{description} would exceed the Windows MAX_PATH limit "
            f"({len(path_text) + 1}/260 including terminator): {path_text}. "
            "Choose a shorter external --output-root, such as C:/z100_hw."
        )


def lexical_absolute(path: Path) -> Path:
    # Keep subst drive letters for writes; resolve only for containment checks.
    return path.expanduser().absolute()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def package_path(relative: str) -> Path:
    value = PurePosixPath(relative.replace("\\", "/"))
    if value.is_absolute() or any(part in ("", ".", "..") for part in value.parts):
        raise ValueError(f"Unsafe package path: {relative!r}")
    path = (BUNDLE / Path(*value.parts)).resolve(strict=True)
    path.relative_to(BUNDLE.resolve())
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def active_tcl_text(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def check_bundle() -> dict[str, Any]:
    manifest = read_json(package_path("manifest.json"))
    if manifest.get("schema") != PACKAGE_SCHEMA:
        raise ValueError("Unsupported hardware source package schema")
    if (
        manifest.get("part") != "xc7z100ffg900-2"
        or manifest.get("vivado_version") != "2026.1"
        or manifest.get("period_ns") != 10
        or manifest.get("sites") != 12
        or manifest.get("dsp48e1_count") != 1252
        or manifest.get("incremental_checkpoint_required") is not False
    ):
        raise ValueError("Unexpected hardware identity in package manifest")
    if manifest.get("windows_path_preflight") != WINDOWS_PATH_PREFLIGHT:
        raise ValueError("Windows MAX_PATH preflight metadata mismatch")

    upstream_path = package_path(UPSTREAM_MANIFEST)
    if sha256(upstream_path) != manifest.get("upstream_manifest_sha256"):
        raise ValueError("Upstream source manifest hash mismatch")
    upstream = read_json(upstream_path)
    if (
        upstream.get("part") != manifest["part"]
        or upstream.get("period_ns") != manifest["period_ns"]
        or upstream.get("sites") != manifest["sites"]
    ):
        raise ValueError("Package and upstream hardware identity disagree")

    source_records = upstream.get("sources")
    if not isinstance(source_records, dict) or len(source_records) != 53:
        raise ValueError("The upstream manifest must describe exactly 53 RTL/ROM inputs")
    if manifest.get("source_count") != len(source_records):
        raise ValueError("Package source count disagrees with the upstream manifest")
    expected_source_names = set(source_records)
    project_rtl = PROJECT_ROOT / "src" / "rtl" / "current"
    project_names = {
        path.name
        for path in project_rtl.iterdir()
        if path.is_file() and path.suffix.lower() in {".sv", ".hex"}
    }
    if project_names != expected_source_names:
        raise ValueError(
            "src/rtl/current input inventory differs from the pinned 53-file source set"
        )
    bundle_rtl = BUNDLE / SOURCE_ROOT
    bundle_names = {
        path.name
        for path in bundle_rtl.iterdir()
        if path.is_file() and path.suffix.lower() in {".sv", ".hex"}
    }
    if bundle_names != expected_source_names:
        raise ValueError("Packaged RTL/ROM inventory differs from the upstream manifest")
    for name, record in source_records.items():
        expected = record.get("sha256")
        if not isinstance(expected, str):
            raise ValueError(f"Missing source hash for {name}")
        for path in (project_rtl / name, bundle_rtl / name):
            if sha256(path) != expected:
                raise ValueError(f"Source hash mismatch: {path}")

    support_records = upstream.get("support")
    expected_scripts = {
        "impl.tcl": "impl.tcl",
        "system_bd.tcl": "system_bd.tcl",
        "s12_directives.tcl": "rtl/s12_directives.tcl",
        "physopt.tcl": "tcl/physopt.tcl",
        "export.tcl": "tcl/export.tcl",
    }
    if not isinstance(support_records, dict) or set(support_records) != set(expected_scripts):
        raise ValueError("The upstream manifest must pin all five required Tcl scripts")
    package_scripts = manifest.get("scripts")
    if not isinstance(package_scripts, dict) or set(package_scripts) != set(expected_scripts):
        raise ValueError("Package script records differ from the required Tcl set")
    for name, relative in expected_scripts.items():
        record = package_scripts[name]
        if record.get("path") != relative:
            raise ValueError(f"Unexpected package location for {name}")
        expected = support_records[name]
        if record.get("sha256") != expected:
            raise ValueError(f"Package and upstream hashes disagree for {name}")
        if sha256(package_path(relative)) != expected:
            raise ValueError(f"Tcl source hash mismatch: {relative}")

    for relative in expected_scripts.values():
        text = active_tcl_text(package_path(relative))
        if ABSOLUTE_PATH_RE.search(text):
            raise ValueError(f"Absolute machine path in {relative}")
    impl_text = active_tcl_text(package_path("impl.tcl"))
    if re.search(r"(?i)read_checkpoint\s+-incremental", impl_text):
        raise ValueError("The source build must not depend on an incremental checkpoint")
    if manifest.get("readme_sha256") != sha256(package_path("readme.md")):
        raise ValueError("Source bundle readme hash mismatch")

    expected_files = {
        "manifest.json",
        UPSTREAM_MANIFEST,
        "readme.md",
        "impl.tcl",
        "system_bd.tcl",
        "rtl/s12_directives.tcl",
        "tcl/physopt.tcl",
        "tcl/export.tcl",
        *(f"rtl/{name}" for name in expected_source_names),
    }
    actual_files = {
        path.relative_to(BUNDLE).as_posix()
        for path in BUNDLE.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_files:
        raise ValueError(
            "Hardware source package inventory differs; "
            f"unlisted={sorted(actual_files - expected_files)}, "
            f"missing={sorted(expected_files - actual_files)}"
        )

    return {
        "manifest": manifest,
        "upstream": upstream,
        "source_names": sorted(expected_source_names),
    }


def prepare_bundle(checked: dict[str, Any], requested_output: Path | None) -> Path:
    destination = lexical_absolute(requested_output or DEFAULT_PREPARE_DIR)
    package_root = PROJECT_ROOT.resolve()
    try:
        destination.resolve().relative_to(package_root)
    except ValueError:
        pass
    else:
        raise ValueError("Preparation output must be outside the project package")
    if destination.exists():
        raise FileExistsError(
            f"Preparation output already exists; choose a new task output location: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)

    upstream = checked["upstream"]
    source_names = checked["source_names"]
    destination.mkdir()
    shutil.copytree(BUNDLE / SOURCE_ROOT, destination / SOURCE_ROOT)
    shutil.copy2(BUNDLE / "system_bd.tcl", destination / "system_bd.tcl")
    shutil.copy2(BUNDLE / "readme.md", destination / "readme.md")
    shutil.copy2(BUNDLE / UPSTREAM_MANIFEST, destination / "manifest.json")
    shutil.copy2(BUNDLE / "impl.tcl", destination / "impl.tcl")
    shutil.copytree(BUNDLE / "tcl", destination / "tcl")

    for relative in (
        "impl.tcl",
        "system_bd.tcl",
        "rtl/s12_directives.tcl",
        "tcl/physopt.tcl",
        "tcl/export.tcl",
    ):
        text = active_tcl_text(destination / relative)
        if ABSOLUTE_PATH_RE.search(text):
            raise ValueError(f"Unresolved absolute Tcl path after preparation: {relative}")
    if re.search(r"(?i)read_checkpoint\s+-incremental", active_tcl_text(destination / "impl.tcl")):
        raise ValueError("Prepared source flow still requests an incremental checkpoint")

    for name in source_names:
        if sha256(destination / SOURCE_ROOT / name) != upstream["sources"][name]["sha256"]:
            raise ValueError(f"Prepared source hash mismatch: {name}")
    prepared_expected = {
        "readme.md",
        "impl.tcl",
        "system_bd.tcl",
        "manifest.json",
        "rtl/s12_directives.tcl",
        "tcl/physopt.tcl",
        "tcl/export.tcl",
        *(f"rtl/{name}" for name in source_names),
    }
    prepared_actual = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    if prepared_actual != prepared_expected:
        raise ValueError("Prepared source tree contains an unexpected file inventory")

    package_manifest = read_json(BUNDLE / "manifest.json")
    record = {
        "schema": "z100_hardware_source_preparation_v1",
        "status": "PREPARED_NOT_RUN",
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "part": package_manifest["part"],
        "vivado_version": package_manifest["vivado_version"],
        "source_manifest_sha256": sha256(BUNDLE / UPSTREAM_MANIFEST),
        "source_count": len(source_names),
        "source_sha256": {
            name: sha256(destination / SOURCE_ROOT / name) for name in source_names
        },
        "scripts": {
            name: {
                "source_sha256": sha256(BUNDLE / relative),
                "prepared_sha256": sha256(destination / relative),
                "transformation": "byte-identical copy",
            }
            for name, relative in {
                "impl.tcl": "impl.tcl",
                "system_bd.tcl": "system_bd.tcl",
                "s12_directives.tcl": "rtl/s12_directives.tcl",
                "physopt.tcl": "tcl/physopt.tcl",
                "export.tcl": "tcl/export.tcl",
            }.items()
        },
        "incremental_checkpoint_used": False,
        "fresh_synthesis_place_route_executed": False,
        "vivado_executed": False,
        "board_access": False,
    }
    write_json(destination / "prepared_manifest.json", record)
    return destination


def run_vivado_stage(
    stage: str,
    script: Path,
    launcher: Path,
    run_dir: Path,
    environment: dict[str, str],
    state: dict[str, Any],
) -> Path:
    log_path = run_dir / f"{stage}_vivado.log"
    state["current_stage"] = stage
    state["stages"][stage] = {"status": "RUNNING", "log": log_path.name}
    write_json(run_dir / "run.json", state)
    command = [str(launcher), "-mode", "batch", "-nolog", "-nojournal", "-source", str(script)]
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            command,
            cwd=run_dir,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=environment,
            check=False,
        )
    state["stages"][stage].update({"status": "PROCESS_EXITED", "exit_code": completed.returncode})
    write_json(run_dir / "run.json", state)
    if completed.returncode != 0:
        raise RuntimeError(f"Vivado {stage} exited with {completed.returncode}; see {log_path}")
    return log_path


def run_vivado(checked: dict[str, Any], launcher: Path, output_root: Path) -> Path:
    if os.name != "nt":
        raise RuntimeError("Vivado execution is supported only on Windows")
    if launcher.name.lower() != "vivado.bat" or not launcher.is_file():
        raise RuntimeError("Pass the Vivado 2026.1 batch launcher with --vivado")

    output_root = lexical_absolute(output_root)
    try:
        output_root.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("Vivado output must be outside the project package")
    if output_root.exists() and not output_root.is_dir():
        raise NotADirectoryError(output_root)

    run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S.%fZ")
    run_dir = output_root / run_id
    generated_ip_xci = run_dir / LONGEST_BD_XCI_RELATIVE_PATH
    check_windows_max_path(generated_ip_xci, "The longest expected block-design IP path")
    run_dir.mkdir(parents=True)
    source_dir = prepare_bundle(checked, run_dir / "source")
    manifest = checked["manifest"]
    upstream = checked["upstream"]
    state: dict[str, Any] = {
        "schema": "z100_hardware_source_run_v1",
        "status": "PREFLIGHT_PENDING",
        "run_id": run_id,
        "vendor_version_required": manifest["vivado_version"],
        "part": manifest["part"],
        "period_ns": manifest["period_ns"],
        "sites": manifest["sites"],
        "build_mode": "fresh_synthesis_place_route",
        "source_count": len(checked["source_names"]),
        "source_manifest_sha256": sha256(BUNDLE / UPSTREAM_MANIFEST),
        "incremental_checkpoint_used": False,
        "output_artifact_dir": "export/artifacts",
        "stages": {"place": {"status": "PENDING"}, "route": {"status": "PENDING"}},
        "board_access": False,
        "board_programmed": False,
        "automatic_retry": False,
    }
    write_json(run_dir / "run.json", state)

    mutex = SharedMutex()
    try:
        active = process_inventory()
        if active:
            raise RuntimeError(f"Vivado or board tools are active: {active}")
        free_ram, free_disk = resource_status()
        state["resource_gate"] = {
            "free_ram_gib": round(free_ram, 3),
            "free_disk_gib": round(free_disk, 3),
        }
        state["status"] = "RUNNING"
        write_json(run_dir / "run.json", state)

        base_environment = dict(os.environ)
        for name in (
            "Z100_S_STAGE",
            "Z100_S_RTL",
            "Z100_S_BD",
            "Z100_S_OUT",
            "Z100_S_SITES",
            "Z100_S_PLACE_DCP",
            "Z100_HARDWARE_OUTPUT",
            "Z100_HARDWARE_INPUT_DCP",
            "Z100_HARDWARE_INPUT_LABEL",
            "Z100_HARDWARE_EXPORT_DCP",
            "Z100_HARDWARE_EXPORT_LABEL",
            "Z100_HARDWARE_EXPORT_SHA256",
            "Z100_HARDWARE_PHYSOPT_SHA256",
        ):
            base_environment.pop(name, None)
        base_environment.update(
            XILINX_LOCAL_USER_DATA="no",
            OMP_NUM_THREADS="1",
            OPENBLAS_NUM_THREADS="1",
            MKL_NUM_THREADS="1",
            Z100_S_RTL=str(source_dir / "rtl"),
            Z100_S_BD=str(source_dir / "system_bd.tcl"),
            Z100_S_SITES="12",
        )

        place_dir = run_dir / "place"
        place_dir.mkdir()
        place_environment = dict(base_environment, Z100_S_STAGE="place", Z100_S_OUT=str(place_dir))
        place_log = run_vivado_stage(
            "place", source_dir / "impl.tcl", launcher, run_dir, place_environment, state
        )
        place_checkpoint = place_dir / "post_place.dcp"
        place_verdict_path = place_dir / "place_verdict.json"
        if not place_checkpoint.is_file() or place_checkpoint.stat().st_size == 0:
            raise RuntimeError("Place stage exited without a nonempty post_place.dcp")
        if not place_verdict_path.is_file():
            raise RuntimeError("Place stage exited without place_verdict.json")
        place_verdict = read_json(place_verdict_path)
        if place_verdict.get("sites") != 12 or place_verdict.get("dsp") != 1252:
            raise RuntimeError(f"Place identity mismatch: {place_verdict}")
        state["stages"]["place"].update(
            {
                "status": "PASS_PLACE_CHECKPOINT",
                "post_place_dcp_sha256": sha256(place_checkpoint),
                "verdict": place_verdict,
                "log": place_log.name,
            }
        )
        write_json(run_dir / "run.json", state)

        route_dir = run_dir / "route"
        route_dir.mkdir()
        route_environment = dict(
            base_environment,
            Z100_S_STAGE="route",
            Z100_S_OUT=str(route_dir),
            Z100_S_PLACE_DCP=str(place_checkpoint),
        )
        route_log = run_vivado_stage(
            "route", source_dir / "impl.tcl", launcher, run_dir, route_environment, state
        )
        route_checkpoint = route_dir / "post_route.dcp"
        route_acceptance_path = route_dir / "acceptance.json"
        if not route_checkpoint.is_file() or route_checkpoint.stat().st_size == 0:
            raise RuntimeError("Route stage exited without a nonempty post_route.dcp")
        if not route_acceptance_path.is_file():
            raise RuntimeError("Route stage exited without acceptance.json")
        route_acceptance = read_json(route_acceptance_path)
        state["stages"]["route"].update(
            {
                "status": "PASS_ROUTE" if route_acceptance.get("pass") is True else "TIMING_REVIEW_REQUIRED",
                "post_route_dcp_sha256": sha256(route_checkpoint),
                "acceptance": route_acceptance,
                "log": route_log.name,
            }
        )
        write_json(run_dir / "run.json", state)

        export_checkpoint = route_checkpoint
        export_label = "route/post_route.dcp"
        if route_acceptance.get("pass") is not True:
            metrics = route_acceptance
            setup_only_candidate = (
                metrics.get("route_completeness_pass") is True
                and metrics.get("drc_error_or_critical") == 0
                and metrics.get("timing_checks_coverage_complete") is True
                and metrics.get("timing_checks_pass") is True
                and metrics.get("unconstrained_internal") == 0
                and float(metrics.get("wns_ns", 0.0)) < 0.0
                and float(metrics.get("whs_ns", -1.0)) >= 0.0
                and float(metrics.get("wpws_ns", -1.0)) >= 0.0
                and float(metrics.get("tpws_ns", -1.0)) >= 0.0
                and metrics.get("setup_fail_endpoints", 0) > 0
                and metrics.get("hold_fail_endpoints", 0) == 0
                and metrics.get("pulse_width_fail_endpoints", -1) == 0
                and metrics.get("pulse_width_total_endpoints", 0) > 0
            )
            if not setup_only_candidate:
                raise RuntimeError(
                    "Route acceptance failed outside the setup-only recovery gate: "
                    f"{metrics}"
                )
            recovery_root = run_dir / "recovery"
            recovery_root.mkdir()
            recovery_environment = dict(
                base_environment,
                Z100_HARDWARE_OUTPUT=str(recovery_root),
                Z100_HARDWARE_INPUT_DCP=str(route_checkpoint),
                Z100_HARDWARE_INPUT_LABEL="route/post_route.dcp",
            )
            recovery_log = run_vivado_stage(
                "physopt",
                source_dir / "tcl" / "physopt.tcl",
                launcher,
                run_dir,
                recovery_environment,
                state,
            )
            recovery_checkpoint = recovery_root / "physopt" / "post_physopt.dcp"
            recovery_acceptance_path = recovery_root / "physopt" / "acceptance.json"
            if not recovery_checkpoint.is_file() or recovery_checkpoint.stat().st_size == 0:
                raise RuntimeError("Explore physopt did not write a nonempty checkpoint")
            if not recovery_acceptance_path.is_file():
                raise RuntimeError("Explore physopt did not write acceptance.json")
            recovery_acceptance = read_json(recovery_acceptance_path)
            if (
                recovery_acceptance.get("status") != "TIMING_ROUTE_DRC_PASS"
                or recovery_acceptance.get("metrics", {}).get("pass") is not True
            ):
                raise RuntimeError(f"Explore physopt failed acceptance: {recovery_acceptance}")
            state["stages"]["physopt"] = {
                "status": "TIMING_ROUTE_DRC_PASS",
                "post_physopt_dcp_sha256": sha256(recovery_checkpoint),
                "acceptance": recovery_acceptance,
                "log": recovery_log.name,
            }
            export_checkpoint = recovery_checkpoint
            export_label = "recovery/physopt/post_physopt.dcp"
            write_json(run_dir / "run.json", state)

        export_environment = dict(
            base_environment,
            Z100_HARDWARE_OUTPUT=str(run_dir),
            Z100_HARDWARE_EXPORT_DCP=str(export_checkpoint),
            Z100_HARDWARE_EXPORT_LABEL=export_label,
            Z100_HARDWARE_EXPORT_SHA256=sha256(export_checkpoint),
        )
        export_log = run_vivado_stage(
            "export", source_dir / "tcl" / "export.tcl", launcher, run_dir, export_environment, state
        )
        export_acceptance_path = run_dir / "export" / "acceptance.json"
        if not export_acceptance_path.is_file():
            raise RuntimeError("Export stage exited without acceptance.json")
        export_acceptance = read_json(export_acceptance_path)
        if (
            export_acceptance.get("status") != "EXPORT_PASS"
            or export_acceptance.get("metrics", {}).get("pass") is not True
            or export_acceptance.get("input_dcp_sha256") != sha256(export_checkpoint)
        ):
            raise RuntimeError(f"Export acceptance failed: {export_acceptance}")
        bit = run_dir / "export" / "artifacts" / "z100_platform.bit"
        xsa = run_dir / "export" / "artifacts" / "z100_platform.xsa"
        if not all(path.is_file() and path.stat().st_size > 0 for path in (bit, xsa)):
            raise RuntimeError("Export acceptance passed without both nonempty deliverables")

        version_text = place_log.read_text(encoding="utf-8", errors="replace")
        version_match = re.search(r"Z100_S12_BUILD version=([^\s]+)", version_text)
        if not version_match or not version_match.group(1).startswith("2026.1"):
            raise RuntimeError("Place log did not prove execution under Vivado 2026.1")
        reference_bit = PROJECT_ROOT / "board" / "artifacts" / "z100_platform.bit"
        state.update(
            {
                "status": "EXPORT_PASS_BOARD_PENDING",
                "current_stage": None,
                "vivado_version": version_match.group(1),
                "source_file_sha256": {
                    name: upstream["sources"][name]["sha256"]
                    for name in checked["source_names"]
                },
                "export_input": {
                    "path": export_label,
                    "sha256": sha256(export_checkpoint),
                },
                "export_acceptance": export_acceptance,
                "export_log": export_log.name,
                "bit": {
                    "path": "export/artifacts/z100_platform.bit",
                    "bytes": bit.stat().st_size,
                    "sha256": sha256(bit),
                    "matches_existing_board_bit": (
                        reference_bit.is_file() and sha256(bit) == sha256(reference_bit)
                    ),
                },
                "xsa": {
                    "path": "export/artifacts/z100_platform.xsa",
                    "bytes": xsa.stat().st_size,
                    "sha256": sha256(xsa),
                },
                "board_access": False,
                "board_programmed": False,
            }
        )
        write_json(run_dir / "run.json", state)
        return run_dir
    except Exception as error:
        state.update(
            {
                "status": "STOPPED_REVIEW_REQUIRED",
                "current_stage": state.get("current_stage"),
                "error": str(error),
                "automatic_retry": False,
                "board_access": False,
            }
        )
        write_json(run_dir / "run.json", state)
        raise
    finally:
        mutex.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="verify package hashes only")
    modes.add_argument("--prepare", action="store_true", help="stage a relocated source tree without running Vivado")
    modes.add_argument("--build", action="store_true", help="run RTL synthesis, place, route, and gated export")
    parser.add_argument("--vivado", type=Path, help="path to the Vivado 2026.1 batch launcher")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="new external destination for --prepare",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="external directory for unique --build run folders",
    )
    args = parser.parse_args()
    if args.output_dir is not None and not args.prepare:
        parser.error("--output-dir is only valid with --prepare")
    if args.prepare and args.output_dir is None:
        parser.error("--prepare requires --output-dir")
    if args.output_root is not None and not args.build:
        parser.error("--output-root is only valid with --build")
    if args.vivado is not None and not args.build:
        parser.error("--vivado is only valid with --build")
    if args.build and args.vivado is None:
        parser.error("--build requires --vivado")

    try:
        checked = check_bundle()
        manifest = checked["manifest"]
        print(
            "PASS hardware source package: "
            f"sources={len(checked['source_names'])}, "
            f"tcl_scripts={len(manifest['scripts'])}, "
            f"incremental_checkpoint=not_required, "
            f"windows_max_path={WINDOWS_MAX_PATH}, "
            "subst_alias_writes=preserved"
        )
        if args.prepare:
            destination = prepare_bundle(checked, args.output_dir)
            print(f"PREPARED source tree: {destination}")
            print("Vivado, synthesis, place, route, and board access were not run.")
        elif args.build:
            run_dir = run_vivado(checked, args.vivado.resolve(), args.output_root or DEFAULT_OUTPUT_ROOT)
            record = read_json(run_dir / "run.json")
            print(
                f"{record['status']}: {run_dir}; "
                "bit=export/artifacts/z100_platform.bit; "
                "xsa=export/artifacts/z100_platform.xsa"
            )
        else:
            print("Check only: Vivado, synthesis, place, route, and board access were not run.")
        return 0
    except Exception as exc:
        print(f"FAIL hardware source package: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
