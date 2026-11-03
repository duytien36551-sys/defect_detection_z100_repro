#!/usr/bin/env python3
"""Import the pinned Claude routed core into the measured plan-ROM shell.

This wrapper binds a single prepared peripheral ROM source package and a
terminal black-box shell synthesis report, then delegates the guarded import
to the unchanged Claude importer. It does not alter the core, platform DCP,
import Tcl, or the base importer's safety checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import import_z100_claude_routed_platform_v1 as original


ROOT = Path(__file__).resolve().parents[1]
BASE_PACKAGE = ROOT / "deployment/hardware/z100_2026/platform_v13c/prepared/conv_pool_guard_v2_20261029"
CANDIDATE_PACKAGE = ROOT / "deployment/hardware/z100_2026/platform_v13c/prepared/plan_rom_bram_v1_20261030"
MANIFEST = CANDIDATE_PACKAGE / "source_manifest.json"
MANIFEST_SHA = "95a0cb82e1c2113385fc37a33322a9dd20336d2f482d1ae26604778167c42439"
BASE_MANIFEST_SHA = "24d31e185bf822a4c477f479594f9549a93d811a11d146b3527efe54e2b63377"
TARGET_SOURCE = "rtl/z100_conv_plan_rom.sv"
EXPECTED_SOURCE_COUNT = 50
EXPECTED_CORE_ROLE_COUNT = 35
EXPECTED_CORE_TOP = "z100_native_row20_shared_pool_address_shared_local_control_v12"
EXPECTED_SHELL_DCP = Path("C:/z100p/ccshell_rom01/shell_post_synth.dcp")
SHELL_EVIDENCE_ROOT = ROOT / "validation/board_z100/plan_rom_bram_blackbox_shell"

ISOLATION = ROOT / "deployment/hardware/z100_2026/platform_v13c/isolation/plan_rom_bram_v1_20261030"
TESTED_CANDIDATE = ISOLATION / "rtl/z100_conv_plan_rom_bram_v1.sv"
TESTBENCH = ISOLATION / "rtl/tb_z100_conv_plan_rom_bram_v1.sv"
VALIDATOR = ROOT / "tools/validate_z100_plan_rom_bram_candidate_v1.py"
PROOF_REPORT = ISOLATION / "runs/20261030T010818.053960Z/result.json"
PROOF_SHA = "0d5fbb0cc23a1d6fbf8161f08282f039feeff9b417995259a4f8c9815a5ea272"
PROVENANCE = CANDIDATE_PACKAGE / "provenance.json"
PROVENANCE_SHA = "5965f79071d1284bc53182bc5711d47fcb474254ad8be585ab7ee59dfca0e316"

EXPECTED_CORE_PATH = Path("C:/z100v13/20261029T022219Z/post_route.dcp")
EXPECTED_CORE_SHA = "ba24e1c0ecdc32de852825e5d6114b3fc5a2d387d51db6c756d029e6de4a179e"
EXPECTED_PLATFORM_PATH = Path("C:/z100p/cpg2_platform_actual01/platform_post_synth.dcp")
EXPECTED_PLATFORM_SHA = "c23daf5ab7b7afe183ce4aadd427dc4973662964a3c0de7c60a9f60ea37373fc"
EXPECTED_ORIGINAL_IMPORTER_SHA = "f13cf2616ba10f37501c3990909f19001a90855adaa857ee8dd906e1117bc51c"


class ImportErrorClosed(RuntimeError):
    """Fail-closed package, evidence, or handoff validation error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_path(path: str | Path) -> str:
    return str(Path(path).resolve()).casefold()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ImportErrorClosed(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError, ImportErrorClosed) as error:
        raise ImportErrorClosed(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise ImportErrorClosed(f"expected JSON object at {path}")
    return value


def package_source_path(package: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise ImportErrorClosed(f"unsafe manifest path: {relative!r}")
    if "\\" in relative or ":" in relative:
        raise ImportErrorClosed(f"manifest path is not normalized: {relative!r}")
    return package.joinpath(*path.parts)


def _validate_manifest_documents(base: dict[str, Any], candidate: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Check manifest structure and prove metadata/core entries are unchanged."""
    base_rows = base.get("sources")
    candidate_rows = candidate.get("sources")
    if not isinstance(base_rows, list) or not isinstance(candidate_rows, list):
        raise ImportErrorClosed("both source manifests must contain source arrays")
    if base.get("source_count") != EXPECTED_SOURCE_COUNT or len(base_rows) != EXPECTED_SOURCE_COUNT:
        raise ImportErrorClosed("original manifest is not the pinned 50-source package")
    if candidate.get("source_count") != EXPECTED_SOURCE_COUNT or len(candidate_rows) != EXPECTED_SOURCE_COUNT:
        raise ImportErrorClosed("candidate manifest is not a 50-source package")
    if {key: value for key, value in base.items() if key != "sources"} != {
        key: value for key, value in candidate.items() if key != "sources"
    }:
        raise ImportErrorClosed("candidate manifest metadata changed outside the source list")
    if base.get("core_top") != EXPECTED_CORE_TOP or base.get("core_sources_unchanged") != EXPECTED_CORE_ROLE_COUNT:
        raise ImportErrorClosed("base manifest core identity/count differs from the pinned package")

    def rows_by_path(rows: list[Any], label: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                raise ImportErrorClosed(f"{label} manifest contains a malformed source row")
            relative = row["path"]
            package_source_path(ROOT, relative)
            if relative in result:
                raise ImportErrorClosed(f"{label} manifest has a duplicate source path: {relative}")
            if not isinstance(row.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
                raise ImportErrorClosed(f"{label} manifest has an invalid SHA-256: {relative}")
            result[relative] = row
        return result

    base_by_path = rows_by_path(base_rows, "base")
    candidate_by_path = rows_by_path(candidate_rows, "candidate")
    if set(base_by_path) != set(candidate_by_path):
        raise ImportErrorClosed("original and candidate source path sets differ")
    base_core = {path: row for path, row in base_by_path.items() if row.get("role") == "core"}
    candidate_core = {path: row for path, row in candidate_by_path.items() if row.get("role") == "core"}
    if len(base_core) != EXPECTED_CORE_ROLE_COUNT or len(candidate_core) != EXPECTED_CORE_ROLE_COUNT:
        raise ImportErrorClosed("expected exactly 35 core-role source entries")
    if base_core != candidate_core:
        raise ImportErrorClosed("one or more core-role manifest entries changed")
    old_target = base_by_path.get(TARGET_SOURCE)
    new_target = candidate_by_path.get(TARGET_SOURCE)
    if old_target is None or new_target is None:
        raise ImportErrorClosed("plan-ROM source is missing from a source manifest")
    if old_target.get("role") != "platform" or new_target.get("role") != "platform":
        raise ImportErrorClosed("plan-ROM source is not a platform-role source")
    changed_rows = sorted(path for path in base_by_path if base_by_path[path] != candidate_by_path[path])
    if changed_rows != [TARGET_SOURCE]:
        raise ImportErrorClosed(f"manifest changes are not isolated to the plan-ROM source: {changed_rows}")
    if set(old_target) != {"path", "role", "sha256", "source"} or set(new_target) != {"path", "role", "sha256", "source"}:
        raise ImportErrorClosed("plan-ROM manifest entry has an unexpected schema")
    return base_by_path, candidate_by_path


def _verify_module_rename(tested_source: bytes, package_source: bytes) -> None:
    old = b"module z100_conv_plan_rom_bram_v1 #("
    new = b"module z100_conv_plan_rom #("
    if tested_source.count(old) != 1:
        raise ImportErrorClosed("tested candidate does not contain one expected module declaration")
    if tested_source.replace(old, new, 1) != package_source:
        raise ImportErrorClosed("prepared ROM differs beyond the single tested module-name rename")


def _validate_proof_gate(
    proof: dict[str, Any], *, candidate_path: Path, baseline_path: Path,
    testbench_path: Path, validator_path: Path, candidate_sha: str, baseline_sha: str,
) -> dict[str, Any]:
    if proof.get("schema") != "z100-plan-rom-bram-candidate-validation-v1/1":
        raise ImportErrorClosed("ROM evidence report schema differs")
    if proof.get("status") != "PASS_DIFFERENTIAL_OOC_MEASURED":
        raise ImportErrorClosed("ROM differential/OOC evidence is not PASS")
    if Path(str(proof.get("candidate", ""))).resolve() != candidate_path.resolve():
        raise ImportErrorClosed("ROM proof candidate path differs from the tested isolated source")
    if Path(str(proof.get("baseline", ""))).resolve() != baseline_path.resolve():
        raise ImportErrorClosed("ROM proof baseline path differs from the frozen package source")
    if proof.get("board_access") is not False or proof.get("placement_or_routing") is not False:
        raise ImportErrorClosed("ROM evidence includes board access or implementation")
    sim = proof.get("simulation") or {}
    required_sim = {
        "status": "PASS_DIFFERENTIAL_CYCLE_EQUIVALENCE", "tiles": 189,
        "negative_cases": 12, "held_cycles": 609, "cancel_cases": 1,
        "latency_cycles": 1, "back_to_back_replacements": 2,
        "reset_request_collisions": 1, "cancel_request_collisions": 1,
        "latency_changed": False,
    }
    if any(sim.get(key) != value for key, value in required_sim.items()):
        raise ImportErrorClosed("ROM proof lacks the required differential simulation coverage")
    synth = proof.get("synthesis") or {}
    if synth.get("status") != "PASS_OOC_SYNTH_MEASURED" or synth.get("return_code") != 0 or synth.get("part") != "xc7z100ffg900-2":
        raise ImportErrorClosed("ROM OOC synthesis was not measured successfully")
    metrics = synth.get("primitive_metrics") or {}
    baseline_metrics = metrics.get("baseline") or {}
    candidate_metrics = metrics.get("candidate") or {}
    delta = synth.get("resource_delta_candidate_minus_baseline") or {}
    if (
        baseline_metrics.get("logic_lut") != 420 or candidate_metrics.get("logic_lut") != 204
        or delta.get("logic_lut") != -216
        or baseline_metrics.get("bram36") != 4 or candidate_metrics.get("bram36") != 1
        or baseline_metrics.get("bram18") != 1 or candidate_metrics.get("bram18") != 1
    ):
        raise ImportErrorClosed("ROM OOC metrics do not match the reviewed LUT reduction")

    before = proof.get("input_sha256_before")
    after = proof.get("input_sha256_after")
    if not isinstance(before, dict) or before != after:
        raise ImportErrorClosed("ROM proof inputs were not stable across validation")
    normalized = {normalized_path(path): digest for path, digest in before.items()}
    required = {
        candidate_path: candidate_sha,
        baseline_path: baseline_sha,
        testbench_path: sha256_file(testbench_path),
        validator_path: sha256_file(validator_path),
    }
    for path, digest in required.items():
        if normalized.get(normalized_path(path)) != digest:
            raise ImportErrorClosed(f"ROM proof does not bind the required input: {path}")
    artifact_hashes = proof.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict) or not artifact_hashes:
        raise ImportErrorClosed("ROM proof has no artifact hashes")
    for raw_path, digest in artifact_hashes.items():
        artifact = Path(raw_path)
        if not artifact.is_file() or sha256_file(artifact) != digest:
            raise ImportErrorClosed(f"ROM proof artifact is missing or changed: {artifact}")
    return {
        "status": proof["status"],
        "report_path": str(PROOF_REPORT.resolve()),
        "report_sha256": sha256_file(PROOF_REPORT),
        "simulation": {key: sim[key] for key in required_sim},
        "primitive_metrics": metrics,
        "limits": ["OOC differential evidence only; no shell integration, placement/routing, board, or performance claim."],
    }


def _load_and_check_package() -> dict[str, Any]:
    if sha256_file(original.MANIFEST) != BASE_MANIFEST_SHA:
        raise ImportErrorClosed("frozen source manifest identity differs from the pinned original")
    if sha256_file(MANIFEST) != MANIFEST_SHA:
        raise ImportErrorClosed("plan-ROM source manifest identity differs from the pinned candidate")
    base = read_json_object(original.MANIFEST)
    candidate = read_json_object(MANIFEST)
    base_by_path, candidate_by_path = _validate_manifest_documents(base, candidate)

    base_hashes: dict[str, str] = {}
    candidate_hashes: dict[str, str] = {}
    byte_changed: list[str] = []
    for relative in sorted(base_by_path):
        old_path = package_source_path(original.MANIFEST.parent, relative)
        new_path = package_source_path(MANIFEST.parent, relative)
        if not old_path.is_file() or not new_path.is_file():
            raise ImportErrorClosed(f"source package file is missing: {relative}")
        old_hash, new_hash = sha256_file(old_path), sha256_file(new_path)
        if old_hash != base_by_path[relative].get("sha256"):
            raise ImportErrorClosed(f"frozen source hash mismatch: {relative}")
        if new_hash != candidate_by_path[relative].get("sha256"):
            raise ImportErrorClosed(f"candidate source hash mismatch: {relative}")
        base_hashes[relative], candidate_hashes[relative] = old_hash, new_hash
        if old_hash != new_hash:
            byte_changed.append(relative)
        if base_by_path[relative].get("role") == "core" and old_hash != new_hash:
            raise ImportErrorClosed(f"core source bytes changed: {relative}")
    if byte_changed != [TARGET_SOURCE]:
        raise ImportErrorClosed(f"expected one noncore byte change, got {byte_changed}")

    target_path = package_source_path(MANIFEST.parent, TARGET_SOURCE)
    target_row = candidate_by_path[TARGET_SOURCE]
    if target_row.get("source") != str(target_path.resolve()):
        raise ImportErrorClosed("candidate manifest does not identify its prepared ROM source")
    if candidate_hashes[TARGET_SOURCE] != sha256_file(target_path):
        raise ImportErrorClosed("prepared plan-ROM source hash is inconsistent")
    _verify_module_rename(TESTED_CANDIDATE.read_bytes(), target_path.read_bytes())

    provenance = read_json_object(PROVENANCE)
    if sha256_file(PROVENANCE) != PROVENANCE_SHA:
        raise ImportErrorClosed("ROM provenance SHA differs from the reviewed candidate package")
    if provenance.get("status") != "PREPARED_MEASURED_ROM_ONLY_NOT_PLATFORM_IMPLEMENTED":
        raise ImportErrorClosed("ROM provenance does not describe a measured, unimplemented candidate")
    if provenance.get("source_manifest_sha256") != MANIFEST_SHA:
        raise ImportErrorClosed("ROM provenance belongs to another source manifest")
    if provenance.get("source_count") != EXPECTED_SOURCE_COUNT or provenance.get("unchanged_core_sources") != EXPECTED_CORE_ROLE_COUNT:
        raise ImportErrorClosed("ROM provenance source/core counts differ")
    if provenance.get("changed_sources") != [TARGET_SOURCE]:
        raise ImportErrorClosed("ROM provenance does not identify the single plan-ROM source change")
    if provenance.get("identity_transform") != "Only module declaration renamed from z100_conv_plan_rom_bram_v1 to z100_conv_plan_rom":
        raise ImportErrorClosed("ROM provenance module-rename description differs")
    if provenance.get("tested_candidate_sha256") != sha256_file(TESTED_CANDIDATE):
        raise ImportErrorClosed("ROM provenance tested-candidate hash differs")
    if provenance.get("integrated_candidate_sha256") != candidate_hashes[TARGET_SOURCE]:
        raise ImportErrorClosed("ROM provenance prepared-source hash differs")
    if Path(provenance.get("validation_report", "")).resolve() != PROOF_REPORT.resolve():
        raise ImportErrorClosed("ROM provenance proof-report path differs")
    proof_sha = sha256_file(PROOF_REPORT)
    if proof_sha != PROOF_SHA:
        raise ImportErrorClosed("ROM validation report SHA differs from the reviewed evidence")
    proof_bindings = provenance.get("evidence_sha256") or {}
    proof_binding_map = {normalized_path(path): digest for path, digest in proof_bindings.items()}
    if proof_binding_map.get(normalized_path(PROOF_REPORT)) != proof_sha:
        raise ImportErrorClosed("ROM provenance does not bind the validation report hash")
    if proof_binding_map.get(normalized_path(TESTED_CANDIDATE)) != sha256_file(TESTED_CANDIDATE):
        raise ImportErrorClosed("ROM provenance does not bind the tested source hash")
    if proof_binding_map.get(normalized_path(TESTBENCH)) != sha256_file(TESTBENCH):
        raise ImportErrorClosed("ROM provenance does not bind the proof testbench")
    proof = read_json_object(PROOF_REPORT)
    proof_summary = _validate_proof_gate(
        proof, candidate_path=TESTED_CANDIDATE,
        baseline_path=package_source_path(original.MANIFEST.parent, TARGET_SOURCE),
        testbench_path=TESTBENCH, validator_path=VALIDATOR,
        candidate_sha=sha256_file(TESTED_CANDIDATE),
        baseline_sha=base_hashes[TARGET_SOURCE],
    )

    if Path(original.CORE).resolve() != EXPECTED_CORE_PATH.resolve() or original.CORE_SHA != EXPECTED_CORE_SHA:
        raise ImportErrorClosed("original importer Claude routed-core identity changed")
    if Path(original.PLATFORM).resolve() != EXPECTED_PLATFORM_PATH.resolve() or original.PLATFORM_SHA != EXPECTED_PLATFORM_SHA:
        raise ImportErrorClosed("original importer PS/HP platform identity changed")
    if sha256_file(Path(original.__file__).resolve()) != EXPECTED_ORIGINAL_IMPORTER_SHA:
        raise ImportErrorClosed("original importer source differs from the inspected guarded implementation")

    return {
        "base_manifest_sha256": BASE_MANIFEST_SHA,
        "candidate_manifest_sha256": MANIFEST_SHA,
        "source_count": EXPECTED_SOURCE_COUNT,
        "core_role_count": EXPECTED_CORE_ROLE_COUNT,
        "changed_noncore_sources": byte_changed,
        "candidate_plan_rom_sha256": candidate_hashes[TARGET_SOURCE],
        "tested_candidate_sha256": sha256_file(TESTED_CANDIDATE),
        "module_rename": "z100_conv_plan_rom_bram_v1 -> z100_conv_plan_rom",
        "rom_candidate_proof": proof_summary,
        "provenance_path": str(PROVENANCE.resolve()),
        "provenance_sha256": sha256_file(PROVENANCE),
        "core_dcp_path": str(EXPECTED_CORE_PATH),
        "core_dcp_sha256_pinned": EXPECTED_CORE_SHA,
        "platform_dcp_path": str(EXPECTED_PLATFORM_PATH),
        "platform_dcp_sha256_pinned": EXPECTED_PLATFORM_SHA,
    }


def _validate_shell_handoff(shell_report_path: Path, package: dict[str, Any]) -> dict[str, str]:
    report_path = Path(shell_report_path).resolve(strict=True)
    expected_root = SHELL_EVIDENCE_ROOT.resolve()
    if not report_path.is_relative_to(expected_root):
        raise ImportErrorClosed("shell report is outside the plan-ROM blackbox-shell evidence directory")
    report = read_json_object(report_path)
    if report.get("status") != "PASS_SHELL_SYNTH_CORE_BLACKBOX_ONLY":
        raise ImportErrorClosed("shell report is not a terminal blackbox-only synthesis result")
    if report.get("source_manifest_sha256") != MANIFEST_SHA:
        raise ImportErrorClosed("shell report belongs to another source manifest")
    if Path(report.get("source_manifest", "")).resolve() != MANIFEST.resolve():
        raise ImportErrorClosed("shell report source-manifest path differs from the candidate package")
    if report.get("input_hashes_unchanged") is not True:
        raise ImportErrorClosed("shell report does not attest stable source hashes during synthesis")
    checks = report.get("checks") or {}
    if checks.get("no_core_body_read_by_vivado") is not True or checks.get("other_unresolved_blackboxes") != 0:
        raise ImportErrorClosed("shell report does not prove the expected isolated blackbox shell")
    if checks.get("blackbox_count") != 1 or checks.get("no_place_route_bitstream_or_board_access") is not True:
        raise ImportErrorClosed("shell report records an unexpected implementation or blackbox state")
    if report.get("core_synthesis_executed") is not False or report.get("core_body_sources_read_by_vivado") != []:
        raise ImportErrorClosed("shell report records core synthesis or core-body source reads")
    if report.get("board_access") is not False or report.get("place_executed") is not False or report.get("route_executed") is not False:
        raise ImportErrorClosed("shell report records physical implementation or board access")
    core_stub = report.get("core_stub") or {}
    if core_stub.get("module") != EXPECTED_CORE_TOP:
        raise ImportErrorClosed("shell core stub module differs from the pinned Claude core top")

    shell = report.get("shell_dcp")
    if not isinstance(shell, dict) or not isinstance(shell.get("path"), str):
        raise ImportErrorClosed("shell report lacks a DCP path/hash record")
    shell_dcp = Path(shell["path"]).resolve(strict=True)
    if normalized_path(shell_dcp) != normalized_path(EXPECTED_SHELL_DCP):
        raise ImportErrorClosed("shell DCP path differs from ccshell_rom01/shell_post_synth.dcp")
    shell_hash = sha256_file(shell_dcp)
    if shell.get("sha256") != shell_hash:
        raise ImportErrorClosed("shell DCP content differs from its report hash")

    report_sources = report.get("source_sha256")
    if not isinstance(report_sources, dict):
        raise ImportErrorClosed("shell report lacks source_sha256 bindings")
    normalized_sources: dict[str, str] = {}
    for path, digest in report_sources.items():
        key = normalized_path(path)
        if key in normalized_sources:
            raise ImportErrorClosed("shell report repeats a source identity under normalized paths")
        normalized_sources[key] = digest
    if normalized_sources.get(normalized_path(MANIFEST)) != MANIFEST_SHA:
        raise ImportErrorClosed("shell report does not bind the candidate manifest file")
    manifest = read_json_object(MANIFEST)
    for row in manifest["sources"]:
        source_path = package_source_path(MANIFEST.parent, row["path"])
        if normalized_sources.get(normalized_path(source_path)) != row["sha256"]:
            raise ImportErrorClosed(f"shell report source binding differs: {row['path']}")
    core_header_rel = "rtl/z100_native_row20_shared_pool_address_shared_v10.sv"
    core_header_sha = next(row["sha256"] for row in manifest["sources"] if row["path"] == core_header_rel)
    if core_stub.get("source_sha256") != core_header_sha:
        raise ImportErrorClosed("shell core-stub header does not match the unchanged core source")
    return {
        "shell_report_path": str(report_path),
        "shell_report_sha256": sha256_file(report_path),
        "shell_dcp_path": str(shell_dcp),
        "shell_dcp_sha256": shell_hash,
    }


def _augment_import_report(run_id: str, package: dict[str, Any], shell: dict[str, str], wrapper_hash_before: str) -> None:
    report_path = ROOT / "validation/board_z100/claude_routed_platform" / run_id / "result.json"
    if not report_path.is_file():
        raise ImportErrorClosed(f"original importer did not produce its run report: {report_path}")
    fresh_package = _load_and_check_package()
    if fresh_package != package:
        raise ImportErrorClosed("ROM package or proof evidence changed during core import")
    fresh_shell = _validate_shell_handoff(Path(shell["shell_report_path"]), fresh_package)
    if fresh_shell != shell:
        raise ImportErrorClosed("shell handoff identity changed during core import")
    wrapper_path = Path(__file__).resolve()
    wrapper_hash_after = sha256_file(wrapper_path)
    if wrapper_hash_after != wrapper_hash_before:
        raise ImportErrorClosed("candidate wrapper source changed during original importer execution")
    report = read_json_object(report_path)
    input_hashes = report.get("input_sha256")
    if not isinstance(input_hashes, dict):
        raise ImportErrorClosed("original importer report lacks input_sha256")
    normalized_inputs = {normalized_path(path): digest for path, digest in input_hashes.items()}
    manifest = read_json_object(MANIFEST)
    required_original_bindings = {
        normalized_path(MANIFEST): MANIFEST_SHA,
        normalized_path(shell["shell_report_path"]): shell["shell_report_sha256"],
        normalized_path(shell["shell_dcp_path"]): shell["shell_dcp_sha256"],
        normalized_path(EXPECTED_CORE_PATH): EXPECTED_CORE_SHA,
        normalized_path(EXPECTED_PLATFORM_PATH): EXPECTED_PLATFORM_SHA,
    }
    required_original_bindings.update({
        normalized_path(package_source_path(MANIFEST.parent, row["path"])): row["sha256"]
        for row in manifest["sources"]
    })
    for path_key, digest in required_original_bindings.items():
        if normalized_inputs.get(path_key) != digest:
            raise ImportErrorClosed("original importer output omitted/changed an import input identity")
    # The base importer only binds its manifest and its Tcl/DCP inputs; attach
    # the ROM proof and all package rows to the final wrapper-owned report.
    input_hashes[str(wrapper_path)] = wrapper_hash_after
    input_hashes[str(PROOF_REPORT.resolve())] = package["rom_candidate_proof"]["report_sha256"]
    input_hashes[str(PROVENANCE.resolve())] = package["provenance_sha256"]
    input_hashes[str(TESTED_CANDIDATE.resolve())] = package["tested_candidate_sha256"]
    input_hashes[str(TESTBENCH.resolve())] = sha256_file(TESTBENCH)
    input_hashes[str(VALIDATOR.resolve())] = sha256_file(VALIDATOR)
    for row in manifest["sources"]:
        source_path = package_source_path(MANIFEST.parent, row["path"])
        input_hashes[str(source_path.resolve())] = row["sha256"]
    base_importer_path = Path(original.__file__).resolve()
    base_importer_hash = sha256_file(base_importer_path)
    if report.get("runner_sha256") != base_importer_hash or base_importer_hash != EXPECTED_ORIGINAL_IMPORTER_SHA:
        raise ImportErrorClosed("original importer source changed during execution")
    input_hashes[str(base_importer_path)] = base_importer_hash
    report["source_manifest_sha256"] = MANIFEST_SHA
    report["candidate_wrapper"] = {"path": str(wrapper_path), "sha256": wrapper_hash_after}
    report["base_importer_source"] = {"path": str(base_importer_path), "sha256": base_importer_hash}
    report["shell_handoff"] = shell
    report["rom_candidate_proof"] = package["rom_candidate_proof"]
    report["rom_source_transform"] = {
        "tested_source_path": str(TESTED_CANDIDATE.resolve()),
        "tested_source_sha256": package["tested_candidate_sha256"],
        "prepared_source_path": str(package_source_path(MANIFEST.parent, TARGET_SOURCE).resolve()),
        "prepared_source_sha256": package["candidate_plan_rom_sha256"],
        "single_change": package["module_rename"],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell-report", type=Path,
                        help="Terminal PASS report from the plan-ROM blackbox shell synthesis")
    parser.add_argument("--run-id", help="Fresh import run id (4-24 letters, digits, or underscores)")
    parser.add_argument("--prepare-only", action="store_true",
                        help="Audit frozen package and optional shell report; no import or vendor call")
    args = parser.parse_args()

    try:
        package = _load_and_check_package()
        wrapper_hash = sha256_file(Path(__file__).resolve())
        shell_binding: dict[str, str] | None = None
        if args.shell_report is not None:
            shell_binding = _validate_shell_handoff(args.shell_report, package)
        if args.prepare_only:
            print(json.dumps({
                "status": "PREPARED_SHELL_HANDOFF_NOT_IMPORTED" if shell_binding else "PREPARED_SOURCE_CLOSURE_WAITING_FOR_SHELL_REPORT",
                "board_access": False,
                "vivado_invoked": False,
                "wrapper_source": str(Path(__file__).resolve()),
                "wrapper_sha256": wrapper_hash,
                "package_identity": package,
                "shell_handoff": shell_binding,
            }, ensure_ascii=False, indent=2))
            return 0
        if not args.shell_report or not args.run_id:
            raise ImportErrorClosed("actual import requires both --shell-report and --run-id")
        if not re.fullmatch(r"[A-Za-z0-9_]{4,24}", args.run_id):
            raise ImportErrorClosed("invalid run id")
        if shell_binding is None:
            raise ImportErrorClosed("shell DCP/report identity did not validate")
        build_dir = Path("C:/z100p") / args.run_id
        report_dir = ROOT / "validation/board_z100/claude_routed_platform" / args.run_id
        if build_dir.exists() or report_dir.exists():
            raise ImportErrorClosed("refusing to reuse an existing import run directory")

        # Change only the manifest inputs consumed by the unchanged guarded
        # importer. Its routed core, platform checkpoint, Tcl and gates remain
        # the authoritative implementation.
        original.MANIFEST = MANIFEST
        original.MANIFEST_SHA = MANIFEST_SHA
        try:
            original.main(argparse.Namespace(
                shell_report=str(Path(args.shell_report).resolve()),
                run_id=args.run_id,
                prepare_only=False,
            ))
        except Exception:
            if report_dir.joinpath("result.json").is_file():
                _augment_import_report(args.run_id, package, shell_binding, wrapper_hash)
            raise
        _augment_import_report(args.run_id, package, shell_binding, wrapper_hash)
        result_path = report_dir / "result.json"
        result = read_json_object(result_path)
        print(json.dumps({
            "status": result.get("status"),
            "import_report": str(result_path),
            "source_manifest_sha256": result.get("source_manifest_sha256"),
            "wrapper_sha256": result.get("candidate_wrapper", {}).get("sha256"),
            "shell_dcp_sha256": result.get("shell_handoff", {}).get("shell_dcp_sha256"),
            "rom_proof_sha256": result.get("rom_candidate_proof", {}).get("report_sha256"),
            "core_dcp_sha256_pinned": EXPECTED_CORE_SHA,
            "platform_dcp_sha256_pinned": EXPECTED_PLATFORM_SHA,
        }, ensure_ascii=False, indent=2))
        return 0
    except (ImportErrorClosed, OSError, KeyError, TypeError, ValueError, StopIteration) as error:
        print(f"FAILED_CLOSED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
