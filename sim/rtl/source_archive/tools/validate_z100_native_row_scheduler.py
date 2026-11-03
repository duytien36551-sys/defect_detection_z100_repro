"""Build host fixtures and validate the private native row scheduler.

The host-only phase binds the current frozen graph and FeatureLayout and
produces direct nested-loop command/window goldens.  A later, separately
created run may perform one XSim run followed by one OOC synthesis if XSim
passes.  This tool does not route, access a board, or make an FPS claim.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

RTL_DIR = ROOT / "deployment/hardware/z100_2026/native_row_scheduler_v1"
RTL = RTL_DIR / "z100_native_row_scheduler.sv"
TB = RTL_DIR / "tb_z100_native_row_scheduler.sv"
SCRIPT = Path(__file__).resolve()
LAYOUT_TOOL = ROOT / "tools/z100_feature_window_layout.py"
PIPELINE = ROOT / "deployment/candidates/pin640/provisional_models/20261022T131845Z_15a161/pipeline"
PACKAGE = PIPELINE / "package/MODEL.V8P"
HEADER = PIPELINE / "package/v8_generated_model.h"
GRAPH = PIPELINE / "model/graph.json"
INPUT = ROOT / "validation/board_z100/pin640_provisional/20261022T131845Z_15a161/host_parity/attempt_02/input_nchw_int8.bin"
EXPECTED_PACKAGE = "96211aa416da6b23955a8b62cca594275daaa4db3e3954632960707c0ec0d44f"
EXPECTED_HEADER = "eb01437b8a70254472c6b06f4798b378644d61789aa72fd516c4c329dea953b5"
EXPECTED_GRAPH = "6ad39858999c9d7bc57b44887ad487f38a1a678d32e887a1c5c89fdcdd34e0b8"
EXPECTED_INPUT = "0d458d68cf3e419e238245193cd5415c75b2931eb011a695c7b5a5765a1718b6"
BUILD_ROOT = ROOT / "deployment/build/z100_native_row_scheduler_v1"
EVIDENCE_ROOT = ROOT / "validation/board_z100/native_row_scheduler_v1"
VIVADO_BIN = Path("C:/appload/2026.1/Vivado/bin")
PART = "xc7z100ffg900-2"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def inventory(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for name, path in sorted(paths.items())}


def source_paths() -> dict[str, Path]:
    return {rel(path): path for path in (RTL, TB, SCRIPT, LAYOUT_TOOL)}


def dependency_paths() -> dict[str, Path]:
    return {rel(path): path for path in (PACKAGE, HEADER, GRAPH, INPUT)}


def snapshot(paths: dict[str, Path], folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=False)
    for name, source in sorted(paths.items()):
        target = folder / (hashlib.sha256(name.encode()).hexdigest()[:8] + "_" + source.name)
        shutil.copy2(source, target)


def write_hex(path: Path, values: list[int], digits: int) -> None:
    path.write_text("".join(f"{value:0{digits}x}\n" for value in values),
                    encoding="ascii", newline="\n")


def pack_fields(fields: list[tuple[int, int]]) -> int:
    value = 0
    for item, width in fields:
        if item < 0 or item >= (1 << width):
            raise ValueError(f"field value {item} does not fit{width}bits")
        value = (value << width) | item
    return value


def unpack_command(command: dict[str, int]) -> list[tuple[int, int]]:
    return [
        (command["epoch"], 32), (command["token_base"], 32),
        (command["tag_base"], 32), (command["channels"], 11),
        (command["input_width"], 10), (command["output_width"], 10),
        (command["kernel"], 2), (command["stride"], 2),
        (command["padding"], 2), (command["lanes"], 6),
        (command["bank_words"], 14), (command["plane_stride"], 14),
        (command["ky_bases"], 42), (command["y_valid"], 3),
    ]


def new_case(*, channels: int, input_width: int, kernel: int, stride: int,
             padding: int, lanes: int, token_base: int, tag_base: int,
             epoch: int = 108, height: int | None = None,
             output_y: int | None = None, y_valid_override: int | None = None,
             base_override: dict[int, int] | None = None) -> dict[str, int]:
    from z100_feature_window_layout import FeatureLayout

    if height is None:
        height = 2 if (channels == 3 and input_width == 640 and kernel == 3) else max(kernel, 3)
    if output_y is None:
        output_y = 0 if height == 2 else min(1, height - 1)
    layout = FeatureLayout(channels, height, input_width)
    if layout.words > 8192:
        raise ValueError("host-valid geometry exceeds the fixed feature-bank depth")
    row_bases = [0, 0, 0]
    ymask = 0
    for ky in range(kernel):
        input_y = output_y * stride + ky - padding
        if 0 <= input_y < height:
            ymask |= 1 << ky
            row_bases[ky] = layout.location(0, input_y, 0)[1]
    if base_override:
        for ky, address in base_override.items():
            row_bases[ky] = address
    if y_valid_override is not None:
        ymask = y_valid_override
    return {
        "epoch": epoch,
        "token_base": token_base,
        "tag_base": tag_base,
        "channels": channels,
        "input_width": input_width,
        "output_width": (input_width + 2 * padding - kernel) // stride + 1,
        "kernel": kernel,
        "stride": stride,
        "padding": padding,
        "lanes": lanes,
        "bank_words": layout.words,
        "plane_stride": height * layout.x_words,
        "ky_bases": sum(address << (14 * ky) for ky, address in enumerate(row_bases)),
        "y_valid": ymask,
        "feature_layout": {"channels": channels, "height": height,
                           "width": input_width, "words": layout.words,
                           "x_words": layout.x_words,
                           "channel_groups": layout.channel_groups,
                           "output_y": output_y},
    }


def base_at(command: dict[str, int], ky: int) -> int:
    return (command["ky_bases"] >> (14 * ky)) & 0x3FFF


def validate_command(command: dict[str, int]) -> tuple[bool, str, int, int]:
    ci, iw, ow = command["channels"], command["input_width"], command["output_width"]
    kernel, stride, padding = command["kernel"], command["stride"], command["padding"]
    if command["token_base"] == 0:
        return False, "zero_token", 0, 0
    if not 1 <= ci <= 1024 or not 1 <= iw <= 640 or not 1 <= ow <= 640:
        return False, "dimension_range", 0, 0
    if kernel not in (1, 3) or stride not in (1, 2) or padding not in (0, 1):
        return False, "kernel_stride_padding", 0, 0
    if not 1 <= command["lanes"] <= 32:
        return False, "lane_range", 0, 0
    if not 1 <= command["bank_words"] <= 8192 or not 1 <= command["plane_stride"] <= 0x3FFF:
        return False, "bank_or_plane_range", 0, 0
    numerator = iw + 2 * padding - kernel
    if numerator < 0:
        return False, "negative_output_extent", 0, 0
    expected_ow = numerator // stride + 1
    if expected_ow != ow:
        return False, "output_width_mismatch", 0, 0
    channel_groups = (ci + 3) // 4
    groups = channel_groups * kernel * kernel
    if not 1 <= groups <= 1024:
        return False, "group_count", 0, 0
    runs = (ow + 11) // 12
    if command["token_base"] + runs - 1 > 0xFFFFFFFF:
        return False, "token_overflow", 0, 0
    if command["tag_base"] + runs * groups - 1 > 0xFFFFFFFF:
        return False, "tag_overflow", 0, 0
    x_words = (iw + 15) // 16
    last_group_offset = (channel_groups - 1) * command["plane_stride"]
    for ky in range(kernel):
        row_end = base_at(command, ky) + last_group_offset + x_words - 1
        if row_end > 0x3FFF:
            return False, "row_address_overflow", 0, 0
        if command["y_valid"] & (1 << ky):
            if row_end >= command["bank_words"] or row_end >= 8192:
                return False, "active_row_out_of_bounds", 0, 0
    return True, "valid", runs, groups


def expected_sequences(command: dict[str, int]) -> tuple[list[int], list[int]]:
    """Direct nested-loop contract, independent from the DUT counter/FSM."""
    from z100_feature_window_layout import FeatureLayout

    valid, reason, runs, groups = validate_command(command)
    if not valid:
        raise ValueError(f"cannot generate expected sequence for {reason}")
    layout = command["feature_layout"]
    feature = FeatureLayout(layout["channels"], layout["height"], layout["width"])
    # Check the independent physical layout mapping used to seed row bases.
    if (feature.words, feature.x_words, feature.channel_groups) != (
            command["bank_words"], (command["input_width"] + 15) // 16,
            (command["channels"] + 3) // 4):
        raise ValueError("FeatureLayout differs from the bound command shape")
    run_words: list[int] = []
    window_words: list[int] = []
    ci_groups = (command["channels"] + 3) // 4
    descriptor_index = 0
    for run_index, output_x in enumerate(range(0, command["output_width"], 12)):
        sites = min(12, command["output_width"] - output_x)
        run_words.append(pack_fields([
            (command["epoch"], 32), (command["token_base"] + run_index, 32),
            (command["lanes"], 6), (sites, 4),
        ]))
        for group4 in range(ci_groups):
            tail = command["channels"] - group4 * 4
            mask = (1 << min(4, tail)) - 1
            for ky in range(command["kernel"]):
                row_address = base_at(command, ky) + group4 * command["plane_stride"]
                for kx in range(command["kernel"]):
                    first_x = output_x * command["stride"] + kx - command["padding"]
                    # The independent FeatureLayout computes the storage row
                    # address for readable coordinates; the caller-provided
                    # base remains the exact address on masked padding rows.
                    if command["y_valid"] & (1 << ky):
                        input_y = (layout["output_y"] * command["stride"] + ky - command["padding"])
                        expected_base = feature.location(min(group4 * 4, command["channels"] - 1),
                                                         input_y, 0)[1]
                        if row_address != expected_base:
                            raise ValueError("row base is inconsistent with FeatureLayout.location")
                    window_words.append(pack_fields([
                        (command["epoch"], 32),
                        (command["tag_base"] + descriptor_index, 32),
                        (row_address, 14), (first_x & 0xFFF, 12),
                        (command["input_width"], 11),
                        (command["output_width"] - output_x, 11),
                        (sites, 4), (mask, 4),
                        (1 if command["stride"] == 2 else 0, 1),
                        (1 if command["y_valid"] & (1 << ky) else 0, 1),
                    ]))
                    descriptor_index += 1
    if len(run_words) != runs or len(window_words) != runs * groups:
        raise RuntimeError("direct-loop golden count differs from command geometry")
    return run_words, window_words


def check_frozen_model() -> dict[str, Any]:
    expected = ((PACKAGE, EXPECTED_PACKAGE), (HEADER, EXPECTED_HEADER),
                (GRAPH, EXPECTED_GRAPH), (INPUT, EXPECTED_INPUT))
    hashes = {}
    for path, digest in expected:
        if not path.is_file() or sha256(path) != digest:
            raise ValueError(f"frozen first-conv dependency identity mismatch: {rel(path)}")
        hashes[rel(path)] = digest
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    first = graph["nodes"][0]
    if (graph.get("input_shape"), first.get("op"), first.get("shape"),
            first.get("params", {}).get("stride"), first.get("params", {}).get("padding"),
            first.get("params", {}).get("dilation"), first.get("params", {}).get("groups")) != (
            [1, 3, 640, 640], "conv", [1, 16, 320, 320], [2, 2], [1, 1], [1, 1], 1):
        raise ValueError("frozen graph first-convolution geometry changed")
    header = HEADER.read_text(encoding="utf-8")
    conv_descriptors = re.findall(r"^\s*(\{\.op=[^\n]+)", header, re.M)
    if not conv_descriptors or not all(
        f".{name}={value}" in conv_descriptors[0]
        for name, value in (("op", "0"), ("c", "16"), ("h", "320"),
                            ("w", "320"), ("kernel", "3"), ("stride", "2"),
                            ("padding", "1"))
    ):
        raise ValueError("generated model header first-conv descriptor changed")
    return {"sha256": hashes, "first_convolution": {
        "input_shape": graph["input_shape"], "output_shape": first["shape"],
        "kernel": 3, "stride": 2, "padding": 1,
        "source": "frozen MODEL.V8P generated header and graph.json"}}


def build_cases() -> tuple[list[tuple[dict[str, int], bool, str]], dict[str, Any]]:
    valid_cases: list[dict[str, int]] = []
    specs = [
        # The frozen actual first convolution and first output row. Its two-row
        # halo is packed with FeatureLayout exactly as the accepted pipeline.
        dict(channels=3, input_width=640, kernel=3, stride=2, padding=1, lanes=16,
             height=2, output_y=0, y_valid_override=0b110),
        dict(channels=1, input_width=1, kernel=1, stride=1, padding=0, lanes=1),
        dict(channels=3, input_width=16, kernel=1, stride=1, padding=0, lanes=3,
             epoch=0),
        dict(channels=4, input_width=17, kernel=3, stride=1, padding=1, lanes=4,
             height=3, output_y=0),
        dict(channels=16, input_width=20, kernel=3, stride=2, padding=1, lanes=16),
        dict(channels=31, input_width=40, kernel=1, stride=2, padding=0, lanes=31),
        dict(channels=33, input_width=40, kernel=3, stride=2, padding=1, lanes=32),
        dict(channels=64, input_width=40, kernel=3, stride=1, padding=1, lanes=32),
        dict(channels=128, input_width=17, kernel=1, stride=2, padding=0, lanes=32),
        dict(channels=256, input_width=640, kernel=1, stride=2, padding=0, lanes=32,
             height=3, output_y=1),
        dict(channels=1024, input_width=1, kernel=1, stride=1, padding=0, lanes=32,
             height=1, output_y=0),
        # Padding-only ky row carries an unused address outside bank_words,
        # while all used rows and every 14-bit descriptor remain valid.
        dict(channels=4, input_width=17, kernel=3, stride=1, padding=1, lanes=4,
             height=3, output_y=0, base_override={0: 100}),
    ]
    for index, spec in enumerate(specs):
        valid_cases.append(new_case(token_base=10000 + index * 100000,
                                    tag_base=1000000 + index * 1000000,
                                    **spec))

    valid_records: list[tuple[dict[str, int], bool, str]] = [(c, True, "valid") for c in valid_cases]
    base = new_case(channels=1, input_width=1, kernel=1, stride=1, padding=0,
                    lanes=1, token_base=7000000, tag_base=8000000)
    base3 = new_case(channels=4, input_width=17, kernel=3, stride=1, padding=1,
                     lanes=4, height=3, output_y=0,
                     token_base=7000100, tag_base=8000100)
    base13 = new_case(channels=1, input_width=13, kernel=1, stride=1, padding=0,
                      lanes=1, token_base=7000200, tag_base=8000200)
    invalid: list[tuple[dict[str, int], bool, str]] = []
    for changes, reason in [
        ({"token_base": 0}, "zero_token"),
        ({"channels": 0}, "dimension_range"),
        ({"input_width": 0}, "dimension_range"),
        ({"output_width": 2}, "output_width_mismatch"),
        ({"kernel": 2}, "kernel_stride_padding"),
        ({"stride": 0}, "kernel_stride_padding"),
        ({"stride": 3}, "kernel_stride_padding"),
        ({"padding": 2}, "kernel_stride_padding"),
        ({"lanes": 0}, "lane_range"),
        ({"lanes": 33}, "lane_range"),
        ({"bank_words": 0}, "bank_or_plane_range"),
        ({"bank_words": 8193}, "bank_or_plane_range"),
        ({"plane_stride": 0}, "bank_or_plane_range"),
        ({"token_base": 0xFFFFFFFF}, "token_overflow"),
        ({"tag_base": 0xFFFFFFFF}, "tag_overflow"),
        ({"ky_bases": 17}, "active_row_out_of_bounds"),
        ({"ky_bases": 8191}, "active_row_out_of_bounds"),
    ]:
        command = copy.deepcopy(base13 if reason in ("token_overflow", "tag_overflow") else base)
        command.update(changes)
        invalid.append((command, False, reason))
    too_many = copy.deepcopy(base)
    too_many.update(channels=1024, kernel=3, padding=1,
                    bank_words=8192, plane_stride=1, ky_bases=(2 << 14) | (1 << 28),
                    y_valid=0b111)
    invalid.append((too_many, False, "group_count"))
    inactive_overflow = copy.deepcopy(base3)
    inactive_overflow.update(channels=8, input_width=1, output_width=1,
                             kernel=3, stride=1, padding=1, bank_words=2,
                             plane_stride=1, ky_bases=(0 << 28) | (0 << 14) | 0x3FFF,
                             y_valid=0b010)
    invalid.append((inactive_overflow, False, "row_address_overflow"))

    records = valid_records + invalid
    counts = {"valid_commands": len(valid_records), "invalid_commands": len(invalid),
              "expected_faults": len(invalid) + 3}
    return records, counts


def generate_fixture(build: Path) -> dict[str, Any]:
    from z100_feature_window_layout import FeatureLayout

    model = check_frozen_model()
    input_bytes = INPUT.read_bytes()
    if len(input_bytes) != 3 * 640 * 640:
        raise ValueError("frozen first-conv input fixture is truncated")
    # Same top two-row halo selected by the native first-row pipeline. Packing
    # is checked through the frozen FeatureLayout helper; data values are not
    # consumed by this scheduling-only RTL.
    tile_chw = b"".join(input_bytes[c * 640 * 640:c * 640 * 640 + 2 * 640]
                       for c in range(3))
    actual_layout = FeatureLayout(3, 2, 640)
    packed_tile = actual_layout.pack(tile_chw)
    if actual_layout.words != 80 or len(packed_tile) != 80 * 64:
        raise ValueError("frozen actual first-conv halo does not pack to80FeatureLayout words")
    if actual_layout.location(0, 0, 0)[1] != 0 or actual_layout.location(0, 1, 0)[1] != 40:
        raise ValueError("FeatureLayout first-conv row bases changed")

    records, counts = build_cases()
    command_words: list[int] = []
    command_meta: list[int] = []
    run_words: list[int] = []
    window_words: list[int] = []
    per_case: list[dict[str, Any]] = []
    for case_index, (command, is_valid, expected_reason) in enumerate(records):
        valid, reason, runs, groups = validate_command(command)
        if valid != is_valid or (not valid and reason != expected_reason):
            raise ValueError(f"host classifier mismatch case={case_index}: "
                             f"expected {expected_reason}, got {reason}; command={command}")
        command_words.append(pack_fields(unpack_command(command)))
        command_meta.append(pack_fields([(1 if valid else 0, 1), (runs if valid else 0, 6),
                                         (groups if valid else 0, 11)]))
        first_run = len(run_words)
        first_window = len(window_words)
        if valid:
            runs_expected, windows_expected = expected_sequences(command)
            run_words.extend(runs_expected)
            window_words.extend(windows_expected)
        per_case.append({"valid": valid, "reason": reason,
                         "runs": runs if valid else 0,
                         "groups_per_run": groups if valid else 0,
                         "run_vector_first": first_run,
                         "window_vector_first": first_window,
                         "command": {key: value for key, value in command.items()
                                     if key != "feature_layout"},
                         "feature_layout": command.get("feature_layout")})

    if (per_case[0]["runs"], per_case[0]["groups_per_run"],
            len(run_words), len(window_words)) != (27, 9, sum(
                item["runs"] for item in per_case if item["valid"]),
                sum(item["runs"] * item["groups_per_run"]
                    for item in per_case if item["valid"])):
        raise ValueError("actual first-conv row must produce exactly27runs and243 descriptors")
    max_group_case = next(item for item in per_case if item["valid"] and
                          item["command"]["channels"] == 1024)
    if max_group_case["groups_per_run"] != 256:
        raise ValueError("K1/CI1024 maximum group geometry was not covered")

    write_hex(build / "commands.hex", command_words, 53)
    write_hex(build / "command_meta.hex", command_meta, 5)
    write_hex(build / "expected_runs.hex", run_words, 19)
    write_hex(build / "expected_windows.hex", window_words, 31)
    (build / "scheduler_defs.vh").write_text(
        f"`define COMMAND_COUNT {len(records)}\n"
        f"`define RUN_COUNT {len(run_words)}\n"
        f"`define WINDOW_COUNT {len(window_words)}\n"
        f"`define VALID_COMMAND_COUNT {counts['valid_commands']}\n"
        f"`define INVALID_COMMAND_COUNT {counts['invalid_commands']}\n"
        f"`define EXPECTED_FAULTS {counts['expected_faults']}\n",
        encoding="ascii", newline="\n")

    # Reread packed words and validate every emitted expected descriptor field
    # against the independent Python records, catching truncation/endianness.
    for path, expected in ((build / "commands.hex", command_words),
                           (build / "expected_runs.hex", run_words),
                           (build / "expected_windows.hex", window_words)):
        parsed = [int(line, 16) for line in path.read_text(encoding="ascii").splitlines()]
        if parsed != expected:
            raise ValueError(f"hex fixture round-trip mismatch: {path.name}")
    return {"status": "PASS", "source_model": model,
            "actual_first_convolution_row": {
                "geometry": {"input_channels": 3, "input_width": 640,
                             "output_width": 320, "kernel": 3, "stride": 2,
                             "padding": 1, "lanes": 16, "sites": 12},
                "feature_layout": {"channels": 3, "height": 2, "width": 640,
                                   "words": actual_layout.words,
                                   "packed_tile_sha256": hashlib.sha256(packed_tile).hexdigest(),
                                   "ky_bases": [0, 0, 40], "y_valid": "110"},
                "runs": per_case[0]["runs"],
                "descriptors": per_case[0]["runs"] * per_case[0]["groups_per_run"]},
            "valid_commands": counts["valid_commands"],
            "invalid_commands": counts["invalid_commands"],
            "expected_runtime_faults": counts["expected_faults"],
            "expected_run_vectors": len(run_words),
            "expected_window_vectors": len(window_words),
            "max_legal_groups_case": {"channels": 1024, "kernel": 1,
                                       "groups": 256},
            "cases": per_case,
            "fixture_sha256": {path.name: sha256(path) for path in (
                build / "commands.hex", build / "command_meta.hex",
                build / "expected_runs.hex", build / "expected_windows.hex",
                build / "scheduler_defs.vh")}}


def phase_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[key] = "1"
    env["VIVADO_MAX_THREADS"] = "2"
    return env


def run_command(name: str, argv: list[str], cwd: Path, env: dict[str, str],
                log: Path, commands: list[dict[str, Any]]) -> str:
    done = subprocess.run(argv, cwd=cwd, env=env, text=True, encoding="utf-8",
                          errors="replace", stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    log.write_text(done.stdout, encoding="utf-8")
    commands.append({"name": name, "argv": argv, "cwd": str(cwd.resolve()),
                     "return_code": done.returncode,
                     "log": rel(log), "log_sha256": sha256(log)})
    if done.returncode:
        raise RuntimeError(f"{name} returned {done.returncode}")
    return done.stdout


def run_xsim(build: Path, evidence: Path, result: dict[str, Any],
             xvlog: Path, xelab: Path, xsim: Path) -> None:
    if not all(tool.is_file() for tool in (xvlog, xelab, xsim)):
        raise FileNotFoundError("Vivado2026.1 XSim launchers are unavailable")
    env = phase_env()
    cwd = build.resolve()
    source_arg = str(RTL.resolve())
    test_arg = str(TB.resolve())
    out = run_command("xvlog", [str(xvlog), "-sv", "-i", str(cwd), source_arg,
                                test_arg], cwd, env, evidence / "xvlog.log", result["commands"])
    if "Parsing SystemVerilog" not in out and "Analyzing SystemVerilog" not in out:
        # Transcript wording differs across Vivado minor builds; successful
        # elaboration and the final marker below remain authoritative.
        result["xvlog_transcript_note"] = "tool returned zero; parser banner wording was not recognized"
    run_command("xelab", [str(xelab), "-debug", "typical", "-top",
                          "tb_z100_native_row_scheduler", "-snapshot",
                          "native_row_scheduler_tb_snapshot"], cwd, env,
                evidence / "xelab.log", result["commands"])
    sim = run_command("xsim", [str(xsim), "native_row_scheduler_tb_snapshot", "-runall"],
                      cwd, env, evidence / "xsim.log", result["commands"])
    marker = re.search(
        r"NATIVE_ROW_SCHEDULER_PASS commands=(\d+) valid_commands=(\d+) invalid_commands=(\d+) "
        r"runs=(\d+) windows=(\d+) run_stalls=(\d+) run_stable=(\d+) "
        r"window_stalls=(\d+) window_stable=(\d+) blocked_reload_polls=(\d+) "
        r"faults=(\d+) aborts=(\d+) done=(\d+)", sim)
    if not marker:
        raise ValueError("XSim PASS marker with exact coverage counters is missing")
    names = ("commands", "valid_commands", "invalid_commands", "runs", "windows",
             "run_stall_cycles", "run_stability_checks", "window_stall_cycles",
             "window_stability_checks", "blocked_reload_polls", "faults", "aborts", "done")
    simulation = dict(zip(names, map(int, marker.groups())))
    expected = result["host_preflight"]["reference"]
    fixed = {"commands": expected["valid_commands"] + expected["invalid_commands"],
             "valid_commands": expected["valid_commands"],
             "invalid_commands": expected["invalid_commands"],
             "runs": expected["expected_run_vectors"],
             "windows": expected["expected_window_vectors"],
             "blocked_reload_polls": 200,
             "faults": expected["expected_runtime_faults"],
             "aborts": 3,
             "done": expected["valid_commands"]}
    if any(simulation.get(key) != value for key, value in fixed.items()):
        raise ValueError(f"XSim coverage differs from host goldens: {simulation} vs {fixed}")
    for key in ("run_stall_cycles", "run_stability_checks", "window_stall_cycles",
                "window_stability_checks"):
        if simulation[key] <= 0:
            raise ValueError(f"XSim backpressure coverage is absent: {key}")
    result["simulation"] = {"status": "PASS", **simulation}


def run_ooc(build: Path, evidence: Path, result: dict[str, Any], vivado: Path) -> None:
    if not vivado.is_file():
        raise FileNotFoundError(f"Vivado2026.1 launcher is unavailable: {vivado}")
    tcl = build / "synth.tcl"
    paths = [RTL.resolve(), evidence.joinpath("utilization.rpt").resolve(),
             build.joinpath("post_synth.dcp").resolve()]
    tcl.write_text(f'''set_param general.maxThreads 2
if {{![string match 2026.1* [version -short]]}} {{error "Requires Vivado2026.1"}}
read_verilog -sv {{{paths[0].as_posix()}}}
synth_design -top z100_native_row_scheduler -part {PART} -mode out_of_context -flatten_hierarchy none
report_utilization -file {{{paths[1].as_posix()}}}
write_checkpoint -force {{{paths[2].as_posix()}}}
set lut_count [llength [get_cells -quiet -hier -filter {{REF_NAME =~ LUT*}}]]
set ff_count [llength [get_cells -quiet -hier -filter {{REF_NAME =~ FD*}}]]
set ram18_count [llength [get_cells -quiet -hier -filter {{REF_NAME =~ RAMB18*}}]]
set ram36_count [llength [get_cells -quiet -hier -filter {{REF_NAME =~ RAMB36*}}]]
set dsp_cells [get_cells -quiet -hier -filter {{REF_NAME =~ DSP*}}]
set latch_count [llength [get_cells -quiet -hier -filter {{REF_NAME =~ LD*}}]]
set blackbox_count [llength [get_cells -quiet -hier -filter {{IS_BLACKBOX == 1}}]]
puts "NATIVE_ROW_SCHEDULER_SYNTH lut=$lut_count ff=$ff_count ram18=$ram18_count ram36=$ram36_count dsp=[llength $dsp_cells] latch=$latch_count blackbox=$blackbox_count"
foreach cell $dsp_cells {{puts "NATIVE_ROW_SCHEDULER_DSP name=[get_property NAME $cell] ref=[get_property REF_NAME $cell]"}}
exit
''', encoding="utf-8", newline="\n")
    out = run_command("vivado_ooc", [str(vivado), "-mode", "batch", "-log",
        str((evidence / "vivado.log").resolve()), "-journal",
        str((evidence / "vivado.jou").resolve()), "-source", str(tcl.resolve())],
        build.resolve(), phase_env(), evidence / "vivado_stdout.log", result["commands"])
    if "Vivado v2026.1" not in out:
        raise ValueError("Vivado2026.1 version banner missing")
    match = re.search(r"NATIVE_ROW_SCHEDULER_SYNTH lut=(\d+) ff=(\d+) ram18=(\d+) "
                      r"ram36=(\d+) dsp=(\d+) latch=(\d+) blackbox=(\d+)", out)
    if not match:
        raise ValueError("OOC primitive census marker missing")
    lut, ff, ram18, ram36, dsp, latch, blackbox = map(int, match.groups())
    report = (evidence / "utilization.rpt").read_text(encoding="utf-8", errors="replace")
    slice_lut = re.search(r"^\|\s*Slice LUTs\*?\s*\|\s*(\d+)\s*\|", report, re.M)
    slice_ff = re.search(r"^\|\s*Slice Registers\s*\|\s*(\d+)\s*\|", report, re.M)
    if not slice_lut or not slice_ff:
        raise ValueError("Vivado utilization report lacks Slice LUT/register rows")
    lut_resource, ff_resource = int(slice_lut.group(1)), int(slice_ff.group(1))
    bram36eq = ram36 + ram18 / 2
    gates = {
        "dsp_zero": dsp == 0,
        "bram_zero": bram36eq == 0,
        "slice_lut_max_10000": lut_resource <= 10000,
        "slice_ff_max_6000": ff_resource <= 6000,
        "latch_zero": latch == 0,
        "blackbox_zero": blackbox == 0,
    }
    result["synthesis"] = {
        "status": "PASS_FIXED_RESOURCE_SCREEN" if all(gates.values()) else "FAIL_FIXED_RESOURCE_SCREEN",
        "primitive_lut_cells": lut, "primitive_ff_cells": ff,
        "slice_luts_including_lutram": lut_resource, "slice_registers": ff_resource,
        "ram18": ram18, "ram36": ram36, "bram36_equivalent": bram36eq,
        "dsp": dsp, "dsp_cells": re.findall(
            r"NATIVE_ROW_SCHEDULER_DSP name=(\S+) ref=(\S+)", out),
        "latch": latch, "blackbox": blackbox,
        "fixed_gates": gates,
        "fixed_limits": {"dsp": 0, "bram36_equivalent": 0,
                         "slice_luts_including_lutram_max": 10000,
                         "slice_registers_max": 6000, "latch": 0, "blackbox": 0},
        "scope": "OOC synthesis only; no placement, route, timing, board, or FPS acceptance",
    }
    if not all(gates.values()):
        raise ValueError(f"fixed OOC resource screen failed: {gates}")


def save_result(path: Path, result: dict[str, Any], build: Path, evidence: Path) -> None:
    result["artifact_sha256"] = {
        rel(item): sha256(item)
        for base in (build, evidence)
        for item in sorted(base.rglob("*"))
        if item.is_file() and item != path
    }
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("host", "all"), required=True)
    parser.add_argument("--host-run-id", help="Required for --phase all; immutable host-preflight run")
    parser.add_argument("--xvlog", type=Path, default=VIVADO_BIN / "xvlog.bat")
    parser.add_argument("--xelab", type=Path, default=VIVADO_BIN / "xelab.bat")
    parser.add_argument("--xsim", type=Path, default=VIVADO_BIN / "xsim.bat")
    parser.add_argument("--vivado", type=Path, default=VIVADO_BIN / "vivado.bat")
    args = parser.parse_args()
    if args.phase == "all" and not args.host_run_id:
        parser.error("--phase all requires --host-run-id")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    build, evidence = BUILD_ROOT / run_id, EVIDENCE_ROOT / run_id
    build.mkdir(parents=True, exist_ok=False)
    evidence.mkdir(parents=True, exist_ok=False)
    result_path = evidence / "result.json"
    result: dict[str, Any] = {
        "run_id": run_id,
        "status": "RUNNING",
        "phase": "HOST_PREFLIGHT" if args.phase == "host" else "XSIM_AND_OOC",
        "objective": "private one-row resident weight-group command scheduler, SITES=12",
        "device_part": PART,
        "board_access": False,
        "route_attempted": False,
        "production_integrated": False,
        "fps_or_frequency_claim": False,
        "vendor_attempts": {"xsim_flows": 0, "ooc_synthesis_flows": 0, "retries": 0},
        "build_directory": str(build.resolve()),
        "evidence_directory": str(evidence.resolve()),
        "commands": [],
    }
    try:
        sources = source_paths()
        deps = dependency_paths()
        source_before = inventory(sources)
        dependency_before = inventory(deps)
        if args.phase == "host":
            result["source_sha256_before"] = source_before
            result["dependency_sha256_before"] = dependency_before
            snapshot(sources, evidence / "source_snapshot")
            snapshot(deps, evidence / "dependency_snapshot")
            reference = generate_fixture(build)
            result["host_preflight"] = {"status": "PASS", "reference": reference,
                                         "source_sha256_after": inventory(sources),
                                         "dependency_sha256_after": inventory(deps)}
            if result["host_preflight"]["source_sha256_after"] != source_before or \
               result["host_preflight"]["dependency_sha256_after"] != dependency_before:
                raise RuntimeError("source or frozen dependency changed during host preflight")
            result["status"] = "PASS_HOST_PREFLIGHT_ONLY"
        else:
            host_evidence = EVIDENCE_ROOT / args.host_run_id
            host_build = BUILD_ROOT / args.host_run_id
            host_path = host_evidence / "result.json"
            if not host_path.is_file() or not host_build.is_dir():
                raise FileNotFoundError("selected immutable host-preflight run is missing")
            host = json.loads(host_path.read_text(encoding="utf-8"))
            if host.get("status") != "PASS_HOST_PREFLIGHT_ONLY":
                raise ValueError("selected run is not a passing host-only preflight")
            if source_before != host.get("source_sha256_before") or \
               dependency_before != host.get("dependency_sha256_before"):
                raise RuntimeError("source/dependency identity differs from reviewed host preflight")
            result["source_sha256_before"] = source_before
            result["dependency_sha256_before"] = dependency_before
            result["host_preflight_binding"] = {"run_id": args.host_run_id,
                "result_path": rel(host_path), "result_sha256": sha256(host_path),
                "fixture_sha256": host["host_preflight"]["reference"]["fixture_sha256"]}
            snapshot(sources, evidence / "source_snapshot")
            snapshot(deps, evidence / "dependency_snapshot")
            for name in ("commands.hex", "command_meta.hex", "expected_runs.hex",
                         "expected_windows.hex", "scheduler_defs.vh"):
                shutil.copy2(host_build / name, build / name)
                if sha256(build / name) != host["host_preflight"]["reference"]["fixture_sha256"].get(name):
                    raise RuntimeError(f"host fixture differs while binding vendor run: {name}")
            result["host_preflight"] = host["host_preflight"]
            result["vendor_attempts"]["xsim_flows"] = 1
            run_xsim(build, evidence, result, args.xvlog, args.xelab, args.xsim)
            result["status"] = "PASS_PRIVATE_NATIVE_ROW_SCHEDULER_XSIM_ONLY"
            result["vendor_attempts"]["ooc_synthesis_flows"] = 1
            run_ooc(build, evidence, result, args.vivado)
            result["status"] = "PASS_PRIVATE_NATIVE_ROW_SCHEDULER_XSIM_OOC_SYNTH_ONLY"

        result["source_sha256_after"] = inventory(source_paths())
        result["dependency_sha256_after"] = inventory(dependency_paths())
        if result["source_sha256_after"] != source_before or \
           result["dependency_sha256_after"] != dependency_before:
            raise RuntimeError("source/frozen dependency changed during validation")
    except Exception as exc:
        result["status"] = "FAILED"
        result["error"] = f"{type(exc).__name__}: {exc}"
    save_result(result_path, result, build, evidence)
    print(json.dumps({"run_id": run_id, "status": result["status"],
                      "result": rel(result_path), "error": result.get("error")},
                     indent=2, sort_keys=True))
    return 0 if result["status"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
