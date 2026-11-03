"""Bind and validate the private two-bank Conv prefetch controller.

The testbench children acknowledge metadata only. This validator does not run
pixel compute, access a board, or claim full-pipeline timing or FPS.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "deployment/hardware/z100_2026/conv_prefetch_control_v1"
RTL = HW / "z100_conv_prefetch_control.sv"
TB = HW / "tb_z100_conv_prefetch_control.sv"
VENDOR = Path("C:/appload/2026.1/Vivado/bin")
PROOF = ROOT / "validation/board_z100/native_row_commands_v2/20261025T062641.961558Z/result.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def repo_path(name: str) -> Path:
    path = (ROOT / name).resolve()
    require(path.is_relative_to(ROOT.resolve()), f"C-plan path escapes repository: {name}")
    return path


def verify_oracle() -> tuple[dict, Path, Path, dict[str, str]]:
    require(PROOF.is_file(), f"missing executed C-plan proof: {PROOF}")
    proof = json.loads(PROOF.read_text(encoding="utf-8"))
    require(proof.get("execution_return_code") == 0, "C row-plan execution did not pass")
    require(proof.get("rows") == 7220 and proof.get("tiles") == 189, "C row-plan row/tile coverage")
    require(proof.get("convolutions") == 63, "C row-plan Conv event coverage")
    require(proof.get("source_sha256_before") == proof.get("source_sha256_after"), "C proof source hashes changed during execution")

    source_hashes = proof.get("source_sha256_after")
    artifact_hashes = proof.get("artifact_sha256")
    require(isinstance(source_hashes, dict) and source_hashes, "C proof source hash table missing")
    require(isinstance(artifact_hashes, dict) and artifact_hashes, "C proof artifact hash table missing")
    expected: dict[str, str] = {**source_hashes, **artifact_hashes}
    require(len(expected) == len(source_hashes) + len(artifact_hashes), "C proof source/artifact path collision")

    oracle_snapshot = {str(PROOF.relative_to(ROOT)): sha256(PROOF)}
    for name, expected_hash in expected.items():
        require(isinstance(name, str) and isinstance(expected_hash, str) and re.fullmatch(r"[0-9a-f]{64}", expected_hash),
                f"invalid C proof digest entry: {name}")
        path = repo_path(name)
        require(path.is_file(), f"missing C proof-bound file: {name}")
        actual_hash = sha256(path)
        require(actual_hash == expected_hash, f"C proof hash mismatch: {name}")
        oracle_snapshot[name] = actual_hash

    header = repo_path(proof["generated_plan"])
    bindings = header.parent / "row_bindings.json"
    require(header.is_file() and bindings.is_file(), "generated C plan or row bindings missing")
    require(str(header.relative_to(ROOT)) in expected and str(bindings.relative_to(ROOT)) in expected,
            "generated C plan and row bindings are not included in proof artifacts")
    return proof, header, bindings, oracle_snapshot


def make_plan(proof: dict, header: Path, bindings_path: Path, build: Path) -> dict:
    header_text = header.read_text(encoding="utf-8")
    match = re.search(r"static\s+const\s+ZnHaloGeometry\s+z100_halos\[189\]\s*=\s*\{(.*?)\};", header_text, re.S)
    require(match is not None, "cannot find 189-entry generated C halo geometry")
    geometry = [[int(value) for value in row.split(",")] for row in re.findall(r"\{([0-9,]+)\}", match.group(1))]
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    tiles = bindings.get("tiles")
    require(isinstance(tiles, list) and len(geometry) == len(tiles) == 189, "C geometry/binding tile cardinality")
    require(all(len(row) == 13 for row in geometry), "C geometry must contain 13 raw fields per tile")

    runs: list[int] = []
    windows: list[int] = []
    event_groups: list[list[int]] = []
    seen_events: set[int] = set()
    previous_event: int | None = None
    expected_output_y = 0
    current_first = 0
    current_count = 0
    current_height = 0

    for tile_index, (row, binding) in enumerate(zip(geometry, tiles)):
        cin, in_h, in_w, in_y, in_rows, out_y, out_rows, out_h, out_w, cout, kernel, stride, padding = row
        require(binding.get("tile") == tile_index, f"C binding tile order at tile {tile_index}")
        require(binding.get("first_output_row") == out_y and binding.get("output_rows") == out_rows,
                f"C binding/geometry output range at tile {tile_index}")
        event = binding.get("event")
        require(isinstance(event, int) and event >= 0, f"C event identity at tile {tile_index}")
        require(cin > 0 and in_h > 0 and in_w > 0 and out_h > 0 and out_w > 0 and cout > 0,
                f"empty C geometry at tile {tile_index}")
        require(in_rows > 0 and in_y + in_rows <= in_h and out_rows > 0 and out_y + out_rows <= out_h,
                f"C geometry bounds at tile {tile_index}")
        require(kernel in (1, 3) and stride in (1, 2) and padding in (0, 1),
                f"unsupported C kernel geometry at tile {tile_index}")

        if event != previous_event:
            if previous_event is not None:
                require(expected_output_y == current_height, f"C event {previous_event} output coverage")
                event_groups.append([current_first, current_count, previous_event, current_height])
            require(event not in seen_events, f"noncontiguous repeated C event id {event}")
            seen_events.add(event)
            previous_event = event
            current_first = tile_index
            current_count = 0
            current_height = out_h
            expected_output_y = 0
        require(out_h == current_height, f"mixed output heights in C event {event}")
        require(out_y == expected_output_y, f"C event {event} output gap/overlap at tile {tile_index}")
        expected_output_y += out_rows
        current_count += 1

        # C-plan token/window allocations are independently derived from the
        # raw geometry fields, not copied from the controller or its outputs.
        tile_runs = ((cout + 31) // 32) * out_rows * ((out_w + 19) // 20)
        tile_windows = tile_runs * ((cin + 3) // 4) * kernel * kernel
        require(0 < tile_runs <= 0xFFFFFFFF and 0 < tile_windows <= 0xFFFFFFFF,
                f"C run/window allocation outside 32-bit range at tile {tile_index}")
        runs.append(tile_runs)
        windows.append(tile_windows)
    require(previous_event is not None and expected_output_y == current_height, "final C event output coverage")
    event_groups.append([current_first, current_count, previous_event, current_height])

    require(len(event_groups) == len(seen_events) == 63, "C plan must contain 63 contiguous Conv events")
    require(sum(group[1] for group in event_groups) == 189, "C plan event groups do not cover all tiles")
    require(sum(runs) == proof.get("runs") == 26380, "independently derived C run total mismatch")
    require(sum(windows) == proof.get("window_requests") == 1659840, "independently derived C window total mismatch")

    def write_words(name: str, values: list[int]) -> None:
        require(all(0 <= value <= 0xFFFFFFFF for value in values), f"fixture word out of range: {name}")
        (build / name).write_text("".join(f"{value:08x}\n" for value in values), encoding="ascii")

    write_words("prefetch_geometry.hex", [value for row in geometry for value in row])
    write_words("prefetch_events.hex", [value for group in event_groups for value in group])
    write_words("prefetch_runs.hex", runs)
    write_words("prefetch_windows.hex", windows)
    return {
        "events": len(event_groups),
        "tiles": len(geometry),
        "rows": proof["rows"],
        "runs": sum(runs),
        "windows": sum(windows),
        "event_groups": event_groups,
        "initial_bank_coverage": [0, 1],
        "fixtures": [
            "prefetch_geometry.hex",
            "prefetch_events.hex",
            "prefetch_runs.hex",
            "prefetch_windows.hex",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true", help="verify the C proof and write expected memory arrays without starting RTL tools")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    generated_at = datetime.now(timezone.utc).isoformat()
    output = ROOT / "validation/board_z100/conv_prefetch_control" / stamp
    build = ROOT / "build" / f"cpc_{stamp[-14:]}"
    output.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    report_path = output / "result.json"

    result: dict = {
        "status": "RUNNING",
        "generated_at_utc": generated_at,
        "build_dir": str(build.relative_to(ROOT)),
        "commands": [],
        "board_access": False,
        "pixel_compute_executed": False,
        "full_pipeline_30fps_accepted": False,
        "scope": (
            "Controller-only test of all 63 C-plan Conv event groups and 189 tiles. "
            "Load and tile acknowledgements are synthetic metadata responses; the test checks held payloads, "
            "independent two-bank ownership, overlap, completion identity, write drain, recovery and overflow. "
            "No pixels, numerical Conv, graph publication, PS/HP traffic, board action or physical FPS claim."
        ),
    }
    source_before: dict[str, str] = {}
    oracle_before: dict[str, str] = {}
    try:
        proof, header, bindings, oracle_before = verify_oracle()
        plan = make_plan(proof, header, bindings, build)
        result.update(
            c_plan_proof=str(PROOF.relative_to(ROOT)),
            generated_plan=str(header.relative_to(ROOT)),
            row_bindings=str(bindings.relative_to(ROOT)),
            plan_coverage={key: value for key, value in plan.items() if key != "event_groups"},
            event_groups=plan["event_groups"],
            oracle_sha256_before=oracle_before,
        )

        source_files = [Path(__file__).resolve(), TB]
        if RTL.is_file():
            source_files.append(RTL)
        source_before = {str(path.relative_to(ROOT)): sha256(path) for path in source_files if path.is_file()}
        require(str(TB.relative_to(ROOT)) in source_before, "owned testbench missing")
        result["source_sha256_before"] = source_before
        report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

        if args.prepare_only:
            result["status"] = "PREPARED_C_PLAN_BOUND_EXPECTED_ARRAYS_NOT_RTL_EXECUTED"
        else:
            require(RTL.is_file(), f"private DUT not present: {RTL}")
            for tool in ("xvlog.bat", "xelab.bat", "xsim.bat"):
                require((VENDOR / tool).is_file(), f"required Vivado tool missing: {VENDOR / tool}")

            def run(label: str, argv: list[Path | str]) -> str:
                args_text = list(map(str, argv))
                process = subprocess.run(
                    args_text,
                    cwd=build,
                    env=dict(os.environ, XILINX_LOCAL_USER_DATA="no"),
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                (output / f"{label}.log").write_text(process.stdout, encoding="utf-8", errors="replace")
                result["commands"].append({"label": label, "args": args_text, "return_code": process.returncode})
                require(process.returncode == 0 and not re.search(r"^\s*(?:ERROR:|Fatal:)", process.stdout, re.M), f"strict actual {label} failed")
                return process.stdout

            run("xvlog", [VENDOR / "xvlog.bat", "-sv", RTL, TB])
            run("xelab", [VENDOR / "xelab.bat", "-mt", "2", "tb_z100_conv_prefetch_control", "-s", "prefetch_control_sim"])
            simulation_log = run("xsim", [VENDOR / "xsim.bat", "prefetch_control_sim", "-runall"])
            markers = re.findall(r"^CONV_PREFETCH_CONTROL_PASS (.+)$", simulation_log, re.M)
            require(len(markers) == 1, "missing or duplicated complete C-plan coverage marker")
            simulation = {key: int(value) for key, value in re.findall(r"([A-Za-z_]+)=(\d+)", markers[0])}
            require(simulation.get("events") == 63 and simulation.get("tiles") == 189, "actual C-plan event/tile coverage")
            require(simulation.get("negative_cases") == 26 and simulation.get("recovery_blocks") == 9, "actual negative/recovery coverage")
            require(simulation.get("runs") == 26380 and simulation.get("windows") == 1659840, "actual C-plan allocation coverage")
            require(simulation.get("overlap_cycles", 0) > 0, "no prefetch/compute overlap observed")
            require(simulation.get("held_load_cycles", 0) > 0 and simulation.get("held_tile_cycles", 0) > 0,
                    "load and tile backpressure coverage missing")
            require(simulation.get("held_load_on_tile_done", 0) > 0 and simulation.get("held_tile_on_load_done", 0) > 0,
                    "held commands were not covered across opposite child completions")
            result.update(
                status="PASS_CONTROLLER_ONLY_C_PLAN_63_EVENTS189_TILES_SYNTHETIC_CHILDREN_XSIM",
                simulation=simulation,
            )
    except Exception as exc:  # Fail closed and leave an inspectable report.
        result.update(status="FAILED_CLOSED", error=f"{type(exc).__name__}: {exc}")

    current_sources = {name: sha256(repo_path(name)) for name in source_before}
    result["source_sha256_before"] = source_before
    result["source_sha256_after"] = current_sources
    if source_before and current_sources != source_before:
        result.update(status="FAILED_SOURCE_INTEGRITY", error="owned validation source changed during execution")

    if oracle_before:
        oracle_after = {name: sha256(repo_path(name)) for name in oracle_before}
        result["oracle_sha256_before"] = oracle_before
        result["oracle_sha256_after"] = oracle_after
        if oracle_after != oracle_before:
            result.update(status="FAILED_C_PLAN_SOURCE_INTEGRITY", error="executed C-plan source/artifact changed during validation")

    result["artifact_sha256"] = {
        str(path.relative_to(ROOT)): sha256(path)
        for folder in (output, build)
        for path in folder.rglob("*")
        if path.is_file() and path != report_path
    }
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": str(report_path.relative_to(ROOT)), "error": result.get("error")}))
    return int(result["status"].startswith("FAILED"))


if __name__ == "__main__":
    raise SystemExit(main())
