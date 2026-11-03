"""Bind and run the real C-plan ROM -> two-bank prefetch metadata integration."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "deployment/hardware/z100_2026"
NEW_HW = HW / "conv_rom_prefetch_v1"
ROM_HW = HW / "conv_plan_rom_v1"
CTRL_HW = HW / "conv_prefetch_control_v2"
LOCAL = ROOT / "deployment/build/local_tools/iverilog13_msys2"
MANIFEST = LOCAL / "manifest.json"
C_PROOF = ROOT / "validation/board_z100/native_row_commands_v2/20261025T062641.961558Z/result.json"
ROM_ICARUS_PROOF = ROOT / "validation/board_z100/icarus_control/20261026T010501.620894Z/result.json"
CTRL_ICARUS_PROOF = ROOT / "validation/board_z100/icarus_control/20261026T011555.727758Z/result.json"
ROW_HEADER = ROOT / "deployment/build/z100_native_row_commands_v2/20261025T062641.961558Z/row_plan.h"
ROW_BINDINGS = ROW_HEADER.parent / "row_bindings.json"
MODEL_PACKAGE = ROOT / "deployment/candidates/pin640/quant_candidates/epoch200_head_concat_20261024T103836.103919Z/package/MODEL.V8P"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def repo_path(name: str) -> Path:
    path = (ROOT / Path(name)).resolve()
    require(path.is_relative_to(ROOT.resolve()), f"proof-bound path escapes the repository: {name}")
    return path


def verify_report(path: Path, required_status: str | None = None) -> tuple[dict, dict[str, str]]:
    require(path.is_file(), f"missing proof report: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    if required_status is not None:
        require(report.get("status") == required_status, f"proof status changed: {path}")
    before = report.get("source_sha256_before")
    after = report.get("source_sha256_after")
    artifacts = report.get("artifact_sha256")
    require(isinstance(before, dict) and before and before == after,
            f"source-integrity window is not closed: {path}")
    require(isinstance(artifacts, dict), f"artifact hash table missing: {path}")
    snapshot = {str(path.relative_to(ROOT)): sha256(path)}
    for name, digest in {**before, **artifacts}.items():
        require(isinstance(name, str) and re.fullmatch(r"[0-9a-f]{64}", str(digest)),
                f"invalid proof digest entry: {name}")
        source = repo_path(name)
        require(source.is_file() and sha256(source) == digest, f"proof-bound input changed: {name}")
        snapshot[name] = digest
    return report, snapshot


def make_fixtures(build: Path, proof: dict) -> dict:
    require(proof.get("execution_return_code") == 0, "executed C halo-plan proof did not pass")
    require(proof.get("rows") == 7220 and proof.get("tiles") == 189 and
            proof.get("convolutions") == 63 and proof.get("runs") == 26380 and
            proof.get("window_requests") == 1659840, "C halo-plan totals changed")
    header = repo_path(proof["generated_plan"])
    binding_path = header.parent / "row_bindings.json"
    require(header == ROW_HEADER and binding_path == ROW_BINDINGS, "C-plan source location changed")
    text = header.read_text(encoding="utf-8")
    match = re.search(r"static\s+const\s+ZnHaloGeometry\s+z100_halos\[189\]\s*=\s*\{(.*?)\};", text, re.S)
    require(match is not None, "could not find generated 189-entry C halo table")
    geometry = [[int(value) for value in row.split(",")]
                for row in re.findall(r"\{([0-9,]+)\}", match.group(1))]
    bindings = json.loads(binding_path.read_text(encoding="utf-8"))
    tiles = bindings.get("tiles")
    require(isinstance(tiles, list) and len(geometry) == len(tiles) == 189,
            "raw C halo fields and parameter bindings do not have 189 rows")

    event_map = [0] * 256
    tile_records = [0] * 256
    expected = []
    seen_events: set[int] = set()
    event_ids: list[int] = []
    run_total = 0
    window_total = 0
    first = 0
    while first < 189:
        event = int(tiles[first]["event"])
        require(0 < event < 163 and event not in seen_events, "Conv events must be unique, nonzero and map-bounded")
        seen_events.add(event)
        event_ids.append(event)
        end = first
        while end < 189 and int(tiles[end]["event"]) == event:
            end += 1
        count = end - first
        require(0 < count <= 189, "invalid C event tile count")
        for tile_index in range(first, end):
            local = tile_index - first
            row = geometry[tile_index]
            tile = tiles[tile_index]
            require(len(row) == 13 and tile.get("tile") == tile_index and
                    tile.get("event") == event, f"C geometry/binding order at tile {tile_index}")
            require(tile.get("first_output_row") == row[5] and tile.get("output_rows") == row[6],
                    f"C output-row binding at tile {tile_index}")
            require(0 <= row[5] < 65536 and 0 < row[6] < 65536,
                    f"C output y/row field width at tile {tile_index}")
            jobs = tile.get("parameter_jobs")
            require(isinstance(jobs, list) and len(jobs) == (row[9] + 31) // 32 and jobs,
                    f"parameter group count at tile {tile_index}")
            job_ids = [int(item) for item in jobs]
            require(job_ids == list(range(job_ids[0], job_ids[0] + len(job_ids))) and
                    0 <= job_ids[0] < 65536, f"parameter-first binding at tile {tile_index}")
            require(all(0 <= value < 65536 for value in row), f"geometry field width at tile {tile_index}")
            runs = ((row[9] + 31) // 32) * row[6] * ((row[8] + 19) // 20)
            windows = runs * ((row[0] + 3) // 4) * row[10] * row[10]
            require(0 < runs <= windows < (1 << 32), f"descriptor count bounds at tile {tile_index}")
            packed_geometry = sum(value << (16 * index) for index, value in enumerate(row))
            record = (event << 304) | (local << 296) | (count << 288) | (packed_geometry << 80) | \
                     (job_ids[0] << 64) | (runs << 32) | windows
            require(record < (1 << 312), "reserved ROM record bits are nonzero")
            tile_records[tile_index] = record
            expected.extend(row + [event, local, count, job_ids[0]])
            run_total += runs
            window_total += windows
        event_map[event] = (count << 8) | first
        first = end

    require(len(event_ids) == 63 and run_total == 26380 and window_total == 1659840,
            "C event/tile/run/window totals do not match frozen oracle")
    build.mkdir(parents=True, exist_ok=False)
    (build / "conv_event_map.hex").write_text("".join(f"{value:04x}\n" for value in event_map), encoding="ascii")
    (build / "conv_tiles.hex").write_text("".join(f"{value:080x}\n" for value in tile_records), encoding="ascii")
    (build / "expected_plan.hex").write_text("".join(f"{value:08x}\n" for value in expected), encoding="ascii")
    return {"events": len(event_ids), "tiles": len(geometry), "runs": run_total,
            "windows": window_total, "conv_events": event_ids,
            "fixture_sha256": {name: sha256(build / name) for name in
                               ("conv_event_map.hex", "conv_tiles.hex", "expected_plan.hex")}}


def verify_local_iverilog() -> tuple[dict, dict[str, str]]:
    require(MANIFEST.is_file(), "project-local Icarus manifest is missing")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    require(manifest.get("schema") == "project-local-iverilog/1" and
            manifest.get("global_environment_changed") is False, "local simulator manifest is untrusted or changed")
    snapshot = {str(MANIFEST.relative_to(ROOT)): sha256(MANIFEST)}
    for name, digest in manifest.get("files", {}).items():
        file_path = LOCAL / Path(name)
        require(file_path.is_file() and sha256(file_path) == digest, f"local Icarus file hash mismatch: {name}")
        snapshot[str(file_path.relative_to(ROOT))] = digest
    binary = LOCAL / "ucrt64/bin"
    backend = LOCAL / "ucrt64/lib/ivl"
    require((binary / "iverilog.exe").is_file() and (binary / "vvp.exe").is_file() and backend.is_dir(),
            "manifest-bound local Icarus executable/backend missing")
    return manifest, snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true",
                        help="generate source-bound plan fixtures and report without compiling/running Icarus")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    report_dir = ROOT / "validation/board_z100/conv_rom_prefetch_v1" / stamp
    build_dir = ROOT / "deployment/build/conv_rom_prefetch_v1" / stamp
    report_dir.mkdir(parents=True, exist_ok=False)
    report_path = report_dir / "result.json"
    before: dict[str, str] = {}
    report = {
        "status": "RUNNING",
        "commands": [],
        "board_access": False,
        "vendor_tools_started": False,
        "pixel_compute_executed": False,
        "full_pipeline_30fps_accepted": False,
        "build_dir": str(build_dir.relative_to(ROOT)),
        "report_dir": str(report_dir.relative_to(ROOT)),
    }

    try:
        ast.parse(Path(__file__).read_text(encoding="utf-8"))
        c_proof, c_hashes = verify_report(C_PROOF, "PASS_HOST_C_V2_ALL189_HALO_ROW_COMMANDS173_BOUND_PARAMETER_JOBS_ZERO_TOKEN_REJECTED_NOT_INFERENCE")
        require(c_proof.get("source_package_sha256") == "65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c",
                "frozen epoch-200 package identity changed")
        require(sha256(MODEL_PACKAGE) == c_proof["source_package_sha256"], "selected model package changed")
        require(struct.unpack_from("<I", MODEL_PACKAGE.read_bytes(), 12)[0] == 2213989717,
                "model CRC and ROM binding differ")

        rom_proof, rom_hashes = verify_report(ROM_ICARUS_PROOF, "PASS_PROJECT_LOCAL_ICARUS_SOURCE_BOUND_CONTROL_TB_ONLY")
        require(rom_proof.get("top") == "tb_z100_conv_plan_rom" and rom_proof.get("marker") == "CONV_PLAN_ROM_PASS" and
                rom_proof.get("simulation", {}).get("tiles") == 189 and
                rom_proof.get("simulation", {}).get("negative_cases") == 11,
                "preserved real-ROM Icarus proof is not complete")
        control_proof, control_hashes = verify_report(CTRL_ICARUS_PROOF, "PASS_PROJECT_LOCAL_ICARUS_SOURCE_BOUND_CONTROL_TB_ONLY")
        control_sim = control_proof.get("simulation", {})
        require(control_proof.get("top") == "tb_z100_conv_prefetch_control_v3" and
                control_proof.get("marker") == "CONV_PREFETCH_CONTROL_PASS" and
                control_sim.get("events") == 63 and control_sim.get("tiles") == 189 and
                control_sim.get("runs") == 26380 and control_sim.get("windows") == 1659840 and
                control_sim.get("overlap_cycles", 0) > 0,
                "preserved independent two-bank controller proof is not complete")

        local_manifest, manifest_hashes = verify_local_iverilog()
        fixture_summary = make_fixtures(build_dir, c_proof)
        preserved_fixture_hashes = {
            Path(name).name: digest for name, digest in rom_proof.get("artifact_sha256", {}).items()
            if Path(name).name in {"conv_event_map.hex", "conv_tiles.hex", "expected_plan.hex"}
        }
        require(set(preserved_fixture_hashes) == {"conv_event_map.hex", "conv_tiles.hex", "expected_plan.hex"},
                "preserved ROM Icarus fixture hashes are incomplete")
        require(fixture_summary["fixture_sha256"] == preserved_fixture_hashes,
                "generated integration fixture differs from the frozen ROM/C-plan proof")
        rtl = [ROM_HW / "z100_conv_plan_rom.sv", CTRL_HW / "z100_conv_prefetch_control_v2.sv",
               NEW_HW / "z100_conv_rom_prefetch.sv", NEW_HW / "tb_z100_conv_rom_prefetch.sv"]
        require(all(path.is_file() for path in rtl), "integrated RTL/testbench closure is incomplete")
        require(sum(bool(re.search(r"\bmodule\s+tb_z100_conv_rom_prefetch\b", path.read_text(encoding="utf-8")))
                    for path in rtl) == 1, "unique integrated TB top is required")
        closure_text = "\n".join(path.read_text(encoding="utf-8") for path in rtl)
        require(not re.search(r"\b(?:DSP48E1|MULT_MACRO|ADDSUB_MACRO)\b", closure_text),
                "metadata-only integration must not instantiate vendor arithmetic")

        before = {
            **c_hashes,
            **rom_hashes,
            **control_hashes,
            **manifest_hashes,
            str(Path(__file__).relative_to(ROOT)): sha256(Path(__file__)),
            **{str(path.relative_to(ROOT)): sha256(path) for path in rtl},
            str(MODEL_PACKAGE.relative_to(ROOT)): sha256(MODEL_PACKAGE),
        }
        report.update(source_sha256_before=before, frozen_c_plan=str(C_PROOF.relative_to(ROOT)),
                      preserved_rom_proof=str(ROM_ICARUS_PROOF.relative_to(ROOT)),
                      preserved_control_proof=str(CTRL_ICARUS_PROOF.relative_to(ROOT)),
                      simulator=local_manifest.get("versions"), top="tb_z100_conv_rom_prefetch",
                      marker="CONV_ROM_PREFETCH_PASS", fixture_summary=fixture_summary,
                      coverage={"real_plan_rom": True, "real_two_bank_controller": True,
                                "synthetic_children_metadata_only": True,
                                "all_63_events_189_tiles": True,
                                "cancel_stages": ["before_ROM_request", "after_ROM_response", "load_pending",
                                                  "tile_pending", "write_drain_pending"],
                                "negative_cases": ["bad_model_crc", "unknown_event", "non_Conv_event",
                                                   "zero_epoch", "job_end_overflow", "wrong_ROM_identity"],
                                "malformed_ROM_mutations": ["reserved_header_bit", "producer_context_invariant"],
                                "source_lease_loss": True, "destination_reservation_loss": True,
                                "load_child_fault": True, "tile_child_fault": True},
                      scope="Actual project-local Icarus simulation of the frozen C-plan ROM connected to the unchanged two-bank prefetch controller. Synthetic load/tile children acknowledge metadata only. No pixels, AXI, board, synthesis, mapped resources, inference result, or physical FPS claim.")
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

        if args.prepare_only:
            report["status"] = "PREPARED_C_PLAN_ROM_PREFETCH_INTEGRATION_NOT_RTL_EXECUTED"
        else:
            binary = LOCAL / "ucrt64/bin"
            backend = LOCAL / "ucrt64/lib/ivl"
            env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ.get("PATH", ""), OMP_NUM_THREADS="1")
            build_vvp = build_dir / "conv_rom_prefetch.vvp"
            commands = [
                ("iverilog", [binary / "iverilog.exe", "-B", backend, "-g2012", "-s",
                              "tb_z100_conv_rom_prefetch", "-o", build_vvp, *rtl]),
                ("vvp", [binary / "vvp.exe", "-M", backend, build_vvp]),
            ]
            last_log = ""
            for label, argv in commands:
                started = time.monotonic()
                proc = subprocess.run(list(map(str, argv)), cwd=build_dir, env=env,
                                      text=True, encoding="utf-8", errors="replace",
                                      capture_output=True, timeout=300)
                elapsed = time.monotonic() - started
                logs = proc.stdout + "\n" + proc.stderr
                (report_dir / f"{label}.log").write_text(logs, encoding="utf-8")
                report["commands"].append({"args": list(map(str, argv)), "return_code": proc.returncode,
                                           "wall_seconds": elapsed})
                require(proc.returncode == 0 and not re.search(r"^\s*(?:ERROR:|FATAL:|sorry:|.*syntax error)", logs,
                                                               re.M | re.I), f"actual {label} failed or emitted a strict diagnostic")
                last_log = logs
            markers = re.findall(r"^CONV_ROM_PREFETCH_PASS(?: (.*))?$", last_log, re.M)
            require(len(markers) == 1, "integrated Icarus run did not emit one complete marker")
            summary = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", markers[0] or "")}
            require(summary.get("events") == 63 and summary.get("tiles") == 189 and
                    summary.get("runs") == 26380 and summary.get("windows") == 1659840 and
                    summary.get("opposite_bank_overlap", 0) > 0 and
                    summary.get("negative_cases", 0) >= 6 and
                    summary.get("mutations") == 2 and summary.get("cancel_recovery", 0) >= 5,
                    "integrated Icarus coverage marker totals do not match the acceptance gate")
            require(summary.get("load_held", 0) > 0 and summary.get("tile_held", 0) > 0 and
                    summary.get("descriptor_held", 0) > 0 and summary.get("lease_loss") == 2 and
                    summary.get("child_faults") == 2,
                    "integrated held-valid or external-lease-loss coverage was not observed")
            report.update(status="PASS_PROJECT_LOCAL_ICARUS_REAL_ROM_PREFETCH_METADATA_TB_ONLY",
                          simulation=summary)
    except Exception as exc:
        report.update(status="FAILED_CLOSED", error=f"{type(exc).__name__}: {exc}")

    report["source_sha256_before"] = before
    report["source_sha256_after"] = {name: sha256(ROOT / Path(name)) for name in before}
    if before != report["source_sha256_after"]:
        report["status"] = "FAILED_SOURCE_INTEGRITY"
        report["error"] = "one or more proof-bound source/oracle/tool files changed during the run"
    if build_dir.exists():
        report["artifact_sha256"] = {
            str(path.relative_to(ROOT)): sha256(path)
            for folder in (report_dir, build_dir)
            for path in folder.rglob("*") if path.is_file() and path != report_path
        }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(report_path),
                      "error": report.get("error"), "build": str(build_dir)}))
    return int(report["status"].startswith("FAILED"))


if __name__ == "__main__":
    raise SystemExit(main())
