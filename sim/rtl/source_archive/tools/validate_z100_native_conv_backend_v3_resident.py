#!/usr/bin/env python3
"""Validate the isolated V3 parameter-residency backend candidate.

This check proves source closure, local elaboration and the residency handshake
fixture.  It deliberately does not claim synthesis, route, DDR, numeric Conv
parity, full-graph execution, or board FPS.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "deployment/hardware/z100_2026"
BASE_DIR = HW / "native_conv_backend_v3"
CANDIDATE_DIR = HW / "native_conv_backend_v3_resident"
MANIFEST = BASE_DIR / "source_manifest.json"
TOP = CANDIDATE_DIR / "z100_native_conv_backend_v3_resident.sv"
RESIDENCY = CANDIDATE_DIR / "z100_parameter_residency_v1.sv"
RESIDENCY_TB = HW / "parameter_residency_v1/tb_z100_parameter_residency_v1.sv"
LOCAL = ROOT / "deployment/build/local_tools/iverilog13_msys2/ucrt64"
VENDOR = Path(r"C:/appload/2026.1/Vivado/data/verilog/src")
EVIDENCE_ROOT = ROOT / "validation/board_z100/native_conv_backend_v3_resident"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(argv: list[str], cwd: Path, log: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=str(cwd), text=True, encoding="utf-8",
                            errors="replace", stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    log.write_text(result.stdout, encoding="utf-8")
    return result


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    evidence = EVIDENCE_ROOT / stamp
    build = ROOT / "deployment/build/native_conv_backend_v3_resident" / stamp
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    report: dict[str, object] = {
        "status": "RUNNING",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "candidate": "native_conv_backend_v3_resident",
        "scope": "isolated parameter residency integration; no synthesis, route, board, numeric parity, full graph, or FPS acceptance",
    }
    issues: list[str] = []
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        original_rel = next(name for name in manifest["synthesis_sources"]
                            if name.replace("\\", "/").endswith(
                                "native_conv_backend_v3/z100_native_conv_backend_v3.sv"))
        original = ROOT / Path(original_rel.replace("\\", "/"))
        if sha256(original) != manifest["synthesis_sources"][original_rel]:
            issues.append("immutable V3 source hash changed")
        if not TOP.is_file() or not RESIDENCY.is_file():
            issues.append("candidate RTL is missing")
        text = TOP.read_text(encoding="utf-8") if TOP.is_file() else ""
        checks = {
            "top_renamed": "module z100_native_conv_backend_v3_resident #(" in text,
            "residency_instantiated": "z100_parameter_residency_v1 parameter_residency" in text,
            "tile_ready_gated_by_residency": "assign parameter_ready = resident_cmd_ready;" in text,
            "directory_command_gated_by_residency": ".cmd_valid(resident_downstream_cmd_valid)" in text,
            "completion_gated_by_residency": "assign parameter_done_valid = resident_done_valid;" in text,
            "generation_key_matches_tile_plan": "assign resident_cmd_generation = destination_generation_q;" in text,
            "original_top_not_modified": sha256(original) == manifest["synthesis_sources"][original_rel],
        }
        report["static_checks"] = checks
        issues.extend(name for name, ok in checks.items() if not ok)

        sources: list[Path] = []
        for relative in manifest["synthesis_sources"]:
            path = ROOT / Path(relative.replace("\\", "/"))
            sources.append(TOP if path == original else path)
        sources.append(RESIDENCY)
        vendor = [VENDOR / "unisims/DSP48E1.v", VENDOR / "unimacro/MULT_MACRO.v", VENDOR / "glbl.v"]
        missing = [str(path) for path in [*sources, *vendor] if not path.is_file()]
        if missing:
            issues.append("missing closure sources: " + ", ".join(missing))

        compiler = LOCAL / "bin/iverilog.exe"
        lib = LOCAL / "lib/ivl"
        if not compiler.is_file():
            issues.append("local Icarus compiler is missing")
        else:
            backend_vvp = build / "backend.vvp"
            result = run([str(compiler), "-B", str(lib), "-g2012", "-Wall",
                          "-s", "z100_native_conv_backend_v3_resident", "-s", "glbl",
                          "-o", str(backend_vvp), *map(str, [*sources, *vendor])],
                         CANDIDATE_DIR, evidence / "backend_iverilog.log")
            report["backend_elaboration"] = {"return_code": result.returncode,
                                               "artifact": str(backend_vvp.relative_to(ROOT))}
            if result.returncode != 0 or not backend_vvp.is_file():
                issues.append("candidate backend elaboration failed")
            if re.search(r"error:|Unknown module|Unable to bind|dangling input|floating", result.stdout, re.I):
                issues.append("candidate backend elaboration has unresolved binding errors")

            tb_vvp = build / "residency_tb.vvp"
            result = run([str(compiler), "-B", str(lib), "-g2012", "-Wall",
                          "-s", "tb_z100_parameter_residency_v1", "-o", str(tb_vvp),
                          str(RESIDENCY), str(RESIDENCY_TB)],
                         CANDIDATE_DIR, evidence / "residency_iverilog.log")
            if result.returncode != 0 or not tb_vvp.is_file():
                issues.append("residency fixture compilation failed")
            else:
                result = run([str(ROOT / "deployment/build/local_tools/iverilog13_msys2/ucrt64/bin/vvp.exe"),
                              str(tb_vvp)], CANDIDATE_DIR, evidence / "residency_vvp.log")
                report["residency_simulation"] = {"return_code": result.returncode,
                                                   "pass_marker": "Z100_PARAMETER_RESIDENCY_V1_PASS" in result.stdout,
                                                   "stdout": result.stdout.strip()}
                if result.returncode != 0 or "Z100_PARAMETER_RESIDENCY_V1_PASS" not in result.stdout:
                    issues.append("residency hit/miss fixture failed")

        candidate_manifest = {
            "schema": "z100-native-conv-source-closure/1",
            "top": "z100_native_conv_backend_v3_resident",
            "status": "LOCAL_ELABORATION_AND_RESIDENCY_PROTOCOL_ONLY",
            "base_manifest": str(MANIFEST.relative_to(ROOT)),
            "candidate_sources": {str(path.relative_to(ROOT)): sha256(path)
                                  for path in [TOP, RESIDENCY]},
            "optimization": "one-entry parameter residency keyed by epoch/event/destination-generation/job",
            "physical_transfer_contract": "directory and parameter reader retain ownership on misses; cache hits issue no DDR command",
            "not_accepted": ["synthesis", "route/timing", "numeric Conv parity", "physical DDR/HP", "full graph", "30 FPS"],
        }
        (CANDIDATE_DIR / "source_manifest_resident.json").write_text(
            json.dumps(candidate_manifest, indent=2) + "\n", encoding="utf-8")
        report["candidate_manifest"] = str((CANDIDATE_DIR / "source_manifest_resident.json").relative_to(ROOT))
        report["source_sha256"] = candidate_manifest["candidate_sources"]
        report["status"] = "PASS_LOCAL_ELAB_RESIDENCY_PROTOCOL_ONLY" if not issues else "FAIL_CLOSED"
        report["issues"] = issues
    except Exception as exc:  # keep a machine-readable failure artifact
        report["status"] = "FAIL_CLOSED"
        report["issues"] = [f"{type(exc).__name__}: {exc}"]
    (evidence / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "evidence": str(evidence),
                      "issues": report.get("issues", [])}, indent=2))
    return 0 if report["status"] == "PASS_LOCAL_ELAB_RESIDENCY_PROTOCOL_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
