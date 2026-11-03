"""Validate the private native32-to-feature-word output packer.

The default run performs host-only frozen-graph and fixture preflight. Pass
--run-vendor only after the shared Vivado slot has been released; that mode
runs exactly one XSim flow and, only on simulation PASS, one OOC synthesis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

for _key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
             "NUMEXPR_NUM_THREADS"):
    os.environ[_key] = "1"

from prepare_z100_pointwise_tables import (  # noqa: E402
    GENERATED_HEADER, GRAPH, parse_header_nodes,
)
from z100_feature_window_layout import FeatureLayout  # noqa: E402
from z100_native_output_layout import (  # noqa: E402
    assemble_scatter, joint_row_tiles, scatter_site_words,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "deployment/hardware/z100_2026/native_output_packer_v1"
RTL = FIXTURE / "z100_native_output_packer.sv"
TB = FIXTURE / "tb_z100_native_output_packer.sv"
LAYOUT = ROOT / "tools/z100_native_output_layout.py"
FEATURE_LAYOUT = ROOT / "tools/z100_feature_window_layout.py"
TABLE_METADATA = ROOT / "tools/prepare_z100_pointwise_tables.py"
PRIOR_LAYOUT_REPORT = ROOT / (
    "validation/board_z100/native_output_layout/"
    "20261023T173935.025837Z/result.json"
)
VIVADO_BIN = Path("C:/appload/2026.1/Vivado/bin")
EXPECTED_GRAPH_SHA256 = "6ad39858999c9d7bc57b44887ad487f38a1a678d32e887a1c5c89fdcdd34e0b8"
EXPECTED_HEADER_SHA256 = "eb01437b8a70254472c6b06f4798b378644d61789aa72fd516c4c329dea953b5"
EXPECTED_LAYOUT_STATUS = "PASS_CURRENT_GRAPH_JOINT_POOL_AND_OUTPUT_SCATTER_HOST_ONLY"
CHANNELS = (1, 3, 9, 16, 31, 32, 33, 64)
WIDTHS = (1, 15, 16, 17, 20, 40, 80, 320)
SITES = (4, 8, 12)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deterministic_chw(channels: int, height: int, width: int, salt: int) -> bytes:
    size = channels * height * width
    return bytes(((i * 37 + (i >> 5) * 11 + salt * 83) ^ (i >> 11) ^ salt) & 255
                 for i in range(size))


def input_vectors(layout: FeatureLayout, chw: bytes, case_index: int):
    """Encode 32 channel bytes per site, poisoning inactive channel tails."""
    result = []
    for group_base in range(0, layout.channels, 32):
        active = min(32, layout.channels - group_base)
        for y in range(layout.height):
            for x in range(layout.width):
                lanes = bytearray(32)
                for lane in range(32):
                    if lane < active:
                        channel = group_base + lane
                        lanes[lane] = chw[(channel * layout.height + y) * layout.width + x]
                    else:
                        # Nonzero poison proves the RTL masks channel tails.
                        lanes[lane] = (0xA5 + lane + x + y + case_index) & 255
                result.append(int.from_bytes(lanes, "little"))
    return result


def verify_scatter(layout: FeatureLayout, chw: bytes, sites: int):
    scattered = list(scatter_site_words(layout, chw, sites))
    packed = assemble_scatter(layout, scattered)
    golden = layout.pack(chw)
    if packed != golden:
        raise ValueError(f"scatter bytes differ from FeatureLayout.pack {(layout.channels, layout.height, layout.width, sites)}")
    if len(scattered) != layout.words or len({address for address, _ in scattered}) != layout.words:
        raise ValueError("scatter has an address duplicate or hole")
    return scattered


def host_check_current_tiles(graph: dict, header_rows: list[dict]):
    plans = []
    bytes_checked = 0
    words_checked = 0
    tiles_checked = 0
    for node in graph["nodes"]:
        if node["op"] != "conv":
            continue
        source_shape = (graph["input_shape"] if node["inputs"][0] == -1
                        else graph["nodes"][node["inputs"][0]]["shape"])
        _, cin, ih, iw = source_shape
        _, cout, oh, ow = node["shape"]
        params = node["params"]
        kernel = header_rows[node["id"]]["kernel"]
        stride = params["stride"][0]
        padding = params["padding"][0]
        tiles = joint_row_tiles(cin, ih, iw, cout, oh, ow, kernel, stride, padding)
        expanded_rows = [row for tile in tiles
                         for row in range(tile["output_first"], tile["output_end"])]
        if expanded_rows != list(range(oh)):
            raise ValueError(f"Joint row partition has missing/duplicate rows at node {node['id']}")
        tile_records = []
        for tile_index, tile in enumerate(tiles):
            tile_height = tile["output_end"] - tile["output_first"]
            layout = FeatureLayout(cout, tile_height, ow)
            if layout.words > layout.bank_depth:
                raise ValueError("Current graph output tile exceeds the 8192-word pool")
            source = deterministic_chw(cout, tile_height, ow,
                                       node["id"] * 101 + tile_index)
            output_words = verify_scatter(layout, source, 12)
            bytes_checked += len(source)
            words_checked += len(output_words)
            tiles_checked += 1
            tile_records.append({**tile,
                                 "source_output_shape_chw": [cout, tile_height, ow],
                                 "source_bytes": len(source),
                                 "scatter_words": len(output_words),
                                 "byte_exact": True})
        plans.append({"node": node["id"], "input_shape_nchw": source_shape,
                      "output_shape_nchw": node["shape"], "kernel": kernel,
                      "stride": stride, "padding": padding, "tiles": tile_records})
    if len(plans) != 63:
        raise ValueError(f"Frozen graph has {len(plans)} conv nodes, expected 63")
    return plans, {"conv_nodes": len(plans), "joint_tiles": tiles_checked,
                   "active_bytes_checked": bytes_checked,
                   "scatter_words_checked": words_checked}


def generate_matrix_fixtures(build: Path):
    """Write direct-CHW stimulus and the independent scatter golden stream."""
    cases = [(c, 3, w, 0) for c in CHANNELS for w in WIDTHS]
    # Keep the matrix at the requested shapes and add a four-channel terminal
    # case specifically to prove that subgroup zero can carry out_last/done.
    # The two existing special indices (51 and 58) remain stable.
    cases.extend(((32, 1, 48, 1), (64, 3, 16, 0), (4, 1, 16, 0)))
    cfg_rows = []
    offset_rows = []
    input_words: list[int] = []
    expected_words: list[int] = []
    case_records = []
    input_cursor = 0
    output_cursor = 0
    matrix_host_checks = 0
    active_bytes = 0
    for case_index, (channels, height, width, special) in enumerate(cases):
        layout = FeatureLayout(channels, height, width)
        source = deterministic_chw(channels, height, width, case_index + 17)
        input_count = ((channels + 31) // 32) * height * width
        words = layout.words
        epoch = 0x200 + case_index
        token_base = 0x1000 + case_index * 4096
        if token_base + ((channels + 31) // 32) * height * ((width + 3) // 4) >= (1 << 32):
            raise ValueError("Fixture token range exceeds the stream token field")
        packed_cfg = (channels | (height << 11) | (width << 21) |
                      (epoch << 31) | (token_base << 63) |
                      (input_count << 95) | (words << 111) | (special << 125))
        cfg_rows.append(f"{packed_cfg:032x}\n")
        offset_rows.append(f"{input_cursor | (output_cursor << 32):016x}\n")

        encoded_inputs = input_vectors(layout, source, case_index)
        if len(encoded_inputs) != input_count:
            raise ValueError("Input fixture count differs from channel-group/row/site dimensions")
        input_words.extend(encoded_inputs)

        for sites in SITES:
            verify_scatter(layout, source, sites)
            matrix_host_checks += 1
        emitted = list(scatter_site_words(layout, source, 12))
        if len(emitted) != words:
            raise ValueError("Golden scatter word count differs from layout")
        for word_index, (address, data) in enumerate(emitted):
            if len(data) != 64:
                raise ValueError("Golden word must contain exactly 64 bytes")
            value = int.from_bytes(data, "little") | (address << 512)
            if word_index == words - 1:
                value |= 1 << 525
            expected_words.append(value)

        case_records.append({"case": case_index, "channels": channels,
                             "height": height, "width": width,
                             "sites_parameterized": list(SITES),
                             "special_full_buffer_pause": bool(special),
                             "epoch": epoch, "token_base": token_base,
                             "input_beats": input_count,
                             "output_words": words,
                             "active_bytes": len(source),
                             "source_sha256": hashlib.sha256(source).hexdigest()})
        input_cursor += input_count
        output_cursor += words
        active_bytes += len(source)

    (build / "native_output_cases.hex").write_text("".join(cfg_rows), encoding="ascii")
    (build / "native_output_offsets.hex").write_text("".join(offset_rows), encoding="ascii")
    (build / "native_output_input.hex").write_text(
        "".join(f"{word:064x}\n" for word in input_words), encoding="ascii")
    (build / "native_output_expected.hex").write_text(
        "".join(f"{word:0132x}\n" for word in expected_words), encoding="ascii")
    (build / "native_output_counts.svh").write_text(
        f"localparam integer CASE_COUNT={len(cases)};\n"
        f"localparam integer INPUT_WORD_COUNT={len(input_words)};\n"
        f"localparam integer EXPECTED_WORD_COUNT={len(expected_words)};\n",
        encoding="ascii")
    return {"cases": len(cases), "matrix_cases": len(CHANNELS) * len(WIDTHS),
            "sites_host_byte_exact_checks": matrix_host_checks,
            "sites_parameters": list(SITES), "input_beats": len(input_words),
            "output_words": len(expected_words), "active_bytes": active_bytes,
            "fixture_files": ["native_output_cases.hex", "native_output_offsets.hex",
                              "native_output_input.hex", "native_output_expected.hex",
                              "native_output_counts.svh"],
            "case_records": case_records}


def validate_negative_guards():
    errors = 0
    layout = FeatureLayout(9, 3, 17)
    data = deterministic_chw(9, 3, 17, 91)
    good = list(scatter_site_words(layout, data, 12))
    bad_sequences = (good[:-1], good + [good[0]],
                     [(layout.words, bytes(64))] + good[1:],
                     [(0, bytes(63))] + good[1:])
    for bad in bad_sequences:
        try:
            assemble_scatter(layout, bad)
        except ValueError:
            errors += 1
        else:
            raise ValueError("Scatter address/length corruption escaped host guard")
    if errors != 4:
        raise ValueError("Expected four independent negative scatter checks")
    return errors


def inventory(root: Path, paths: tuple[Path, ...]):
    return {str(path.relative_to(root)).replace("/", "\\"): sha(path)
            for path in paths}


def snapshot_sources(paths: tuple[Path, ...], target: Path):
    target.mkdir(parents=True, exist_ok=False)
    for path in paths:
        shutil.copy2(path, target / path.name)


def run_logged(name: str, command: list[str], cwd: Path, evidence: Path,
               result: dict, env: dict[str, str]):
    proc = subprocess.run(command, cwd=cwd, env=env, text=True,
                          encoding="utf-8", errors="replace",
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (evidence / f"{name}.log").write_text(proc.stdout, encoding="utf-8")
    result["commands"].append({"name": name, "argv": command,
                               "cwd": str(cwd), "return_code": proc.returncode})
    if proc.returncode:
        raise RuntimeError(f"{name} failed with exit code {proc.returncode}")
    return proc.stdout


def run_vendor(build: Path, evidence: Path, result: dict, env: dict[str, str]):
    for binary in ("xvlog.bat", "xelab.bat", "xsim.bat", "vivado.bat"):
        if not (VIVADO_BIN / binary).is_file():
            raise FileNotFoundError(f"Vivado2026.1 executable missing: {VIVADO_BIN / binary}")
    run_logged("xvlog", [str(VIVADO_BIN / "xvlog.bat"), "-sv", str(RTL), str(TB)],
               build, evidence, result, env)
    run_logged("xelab", [str(VIVADO_BIN / "xelab.bat"), "-mt", "2",
                          "tb_z100_native_output_packer", "-s",
                          "native_output_packer_sim"], build, evidence, result, env)
    simulation = run_logged("xsim", [str(VIVADO_BIN / "xsim.bat"),
                                      "native_output_packer_sim", "-runall"],
                            build, evidence, result, env)
    rows = re.findall(
        r"NATIVE_OUTPUT_PACKER_PASS cases=(\d+) inputs=(\d+) outputs=(\d+) done=(\d+) "
        r"input_bubbles=(\d+) input_stalls=(\d+) input_stability=(\d+) "
        r"output_stalls=(\d+) output_stability=(\d+) full_buffer_checks=(\d+) "
        r"busy_reload_checks=(\d+) max_input_burst=(\d+) max_output_burst=(\d+) "
        r"config_errors=(\d+) input_errors=(\d+) resets=(\d+) cancels=(\d+) "
        r"sites4=1 sites8=1 sites12=1", simulation)
    if len(rows) != 1 or "Fatal:" in simulation:
        raise ValueError("XSim PASS marker missing or simulator reported Fatal")
    (cases, inputs, outputs, done, bubbles, input_stalls, input_stability,
     output_stalls, output_stability, full_checks, reload_checks, max_input,
     max_output, config_errors, input_errors, resets, cancels) = map(int, rows[0])
    if (cases != result["fixtures"]["cases"] or
            inputs < result["fixtures"]["input_beats"] or
            outputs != result["fixtures"]["output_words"] or done != cases or
            min(bubbles, input_stalls, input_stability, output_stalls,
                output_stability, full_checks, reload_checks) <= 0 or
            max_input < 32 or max_output < 8 or config_errors != 4 or
            input_errors != 5 or resets != 1 or cancels != 2):
        raise ValueError("XSim coverage counts do not meet the fixed acceptance gates")
    result["simulation"] = {
        "status": "PASS", "cases": cases, "input_beats": inputs,
        "expected_input_beats": result["fixtures"]["input_beats"],
        "output_words": outputs, "done_count": done,
        "input_bubble_cycles": bubbles, "input_stall_cycles": input_stalls,
        "input_stability_checks": input_stability,
        "output_stall_cycles": output_stalls,
        "output_stability_checks": output_stability,
        "two_buffer_full_checks": full_checks,
        "busy_configuration_reload_checks": reload_checks,
        "max_consecutive_input_beats": max_input,
        "max_consecutive_output_words": max_output,
        "bad_configurations_rejected": config_errors,
        "bad_input_metadata_rejected": input_errors,
        "reset_abort_recovery_cases": resets,
        "cancel_abort_recovery_cases": cancels,
        "sites_parameter_instances": list(SITES),
    }

    tcl = build / "synth.tcl"
    tcl.write_text("""set_param general.maxThreads 2
if {![string match 2026.1* [version -short]]} {error "Requires Vivado2026.1"}
read_verilog -sv {%s}
synth_design -top z100_native_output_packer -part xc7z100ffg900-2 -mode out_of_context -flatten_hierarchy none
create_clock -name packer_clk -period 10.000 [get_ports clk]
report_utilization -file {%s}
report_utilization -hierarchical -file {%s}
write_checkpoint -force {%s}
set lut [llength [get_cells -hier -filter {REF_NAME =~ LUT*}]]
set ff [llength [get_cells -hier -filter {REF_NAME =~ FD*}]]
set ram36 [llength [get_cells -hier -filter {REF_NAME =~ RAMB36*}]]
set ram18 [llength [get_cells -hier -filter {REF_NAME =~ RAMB18*}]]
set dsp [llength [get_cells -hier -filter {REF_NAME =~ DSP*}]]
set latch [llength [get_cells -hier -filter {REF_NAME =~ LD*}]]
set blackbox [llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]
puts "NATIVE_OUTPUT_PACKER_SYNTH lut=$lut ff=$ff ram36=$ram36 ram18=$ram18 dsp=$dsp latch=$latch blackbox=$blackbox"
exit
""" % tuple(path.as_posix() for path in (
        RTL, evidence / "utilization.rpt", evidence / "utilization_hierarchical.rpt",
        build / "post_synth.dcp")), encoding="utf-8")
    synthesis = run_logged(
        "synth", [str(VIVADO_BIN / "vivado.bat"), "-mode", "batch",
                  "-log", str(evidence / "vivado.log"), "-journal",
                  str(evidence / "vivado.jou"), "-source", str(tcl)],
        build, evidence, result, env)
    synth_rows = re.findall(
        r"NATIVE_OUTPUT_PACKER_SYNTH lut=(\d+) ff=(\d+) ram36=(\d+) ram18=(\d+) "
        r"dsp=(\d+) latch=(\d+) blackbox=(\d+)", synthesis)
    if len(synth_rows) != 1:
        raise ValueError("OOC synthesis resource census is missing")
    lut, ff, ram36, ram18, dsp, latch, blackbox = map(int, synth_rows[0])
    bram36_equivalent = ram36 + ram18 / 2
    result["synthesis"] = {"status": "PASS_SCREEN" if (
        lut <= 6000 and ff <= 10000 and bram36_equivalent <= 2 and
        dsp == 0 and latch == 0 and blackbox == 0) else "FAIL_SCREEN",
        "lut": lut, "ff": ff, "ram36": ram36, "ram18": ram18,
        "bram36_equivalent": bram36_equivalent, "dsp": dsp,
        "latch": latch, "blackbox": blackbox,
        "fixed_limits": {"lut_max": 6000, "ff_max": 10000,
                         "bram36_equivalent_max": 2, "dsp": 0,
                         "latch": 0, "blackbox": 0}}
    if result["synthesis"]["status"] != "PASS_SCREEN":
        raise ValueError("OOC synthesis exceeded the fixed resource screen")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--host-only", action="store_true",
                      help="Generate fixtures and run host-only frozen graph checks")
    mode.add_argument("--run-vendor", action="store_true",
                      help="Run exactly one XSim then one OOC synthesis if XSim passes")
    args = parser.parse_args()

    expected_hashes = {GRAPH: EXPECTED_GRAPH_SHA256,
                       GENERATED_HEADER: EXPECTED_HEADER_SHA256}
    for path, expected in expected_hashes.items():
        if sha(path) != expected:
            parser.error(f"Frozen dependency hash mismatch: {path}")
    prior = json.loads(PRIOR_LAYOUT_REPORT.read_text(encoding="utf-8"))
    if prior.get("status") != EXPECTED_LAYOUT_STATUS or prior.get("conv_nodes") != 63:
        parser.error("Pinned native output layout host report is not passing for 63 convs")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    evidence = ROOT / "validation/board_z100/native_output_packer_v1" / run_id
    build = ROOT / "deployment/build/z100_native_output_packer_v1" / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    sources = (RTL, TB, Path(__file__), LAYOUT, FEATURE_LAYOUT, TABLE_METADATA,
               GRAPH, GENERATED_HEADER, PRIOR_LAYOUT_REPORT)
    before = inventory(ROOT, sources)
    result = {"status": "RUNNING", "run_id": run_id,
              "phase": "HOST_PREFLIGHT", "source_sha256_before": before,
              "dependency_report": str(PRIOR_LAYOUT_REPORT.relative_to(ROOT)),
              "dependency_report_sha256": sha(PRIOR_LAYOUT_REPORT),
              "commands": [], "board_access": False, "routing_attempted": False,
              "bitstream_created": False, "production_integrated": False,
              "fps_claim": False}
    snapshot_sources(sources, evidence / "source_snapshot")
    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS"):
        env[key] = "1"

    try:
        graph = json.loads(GRAPH.read_text(encoding="utf-8"))
        header_rows = parse_header_nodes(GENERATED_HEADER.read_text(encoding="utf-8"))
        if len(header_rows) != len(graph["nodes"]):
            raise ValueError("Generated package node metadata count differs from graph")
        tile_plans, tile_counts = host_check_current_tiles(graph, header_rows)
        fixtures = generate_matrix_fixtures(build)
        negative = validate_negative_guards()
        result["graph_current_conv_tiles"] = tile_counts
        result["joint_tile_plans"] = tile_plans
        result["fixtures"] = fixtures
        result["host_negative_scatter_cases_rejected"] = negative
        result["host_preflight"] = {
            "status": "PASS", "current_graph_hash": sha(GRAPH),
            "generated_header_hash": sha(GENERATED_HEADER),
            "previous_layout_report_status": prior["status"],
            "current_conv_nodes": tile_counts["conv_nodes"],
            "current_joint_tiles_byte_exact": tile_counts["joint_tiles"],
            "matrix_shapes": len(CHANNELS) * len(WIDTHS),
            "matrix_site_checks": fixtures["sites_host_byte_exact_checks"],
            "independent_golden": "FeatureLayout.pack from direct CHW bytes",
        }
        result["phase"] = "HOST_PREFLIGHT_PASS"
        (evidence / "launch.json").write_text(json.dumps(result, indent=2) + "\n",
                                               encoding="utf-8")
        if args.run_vendor:
            result["phase"] = "XSim_THEN_OOC_SYNTH"
            run_vendor(build, evidence, result, env)
            result["status"] = "PASS_PRIVATE_NATIVE_OUTPUT_PACKER_XSIM_OOC_SYNTH_ONLY"
        else:
            result["status"] = "PASS_HOST_PREFLIGHT_ONLY_VENDOR_NOT_RUN"
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["error"] = f"{type(exc).__name__}: {exc}"

    after = inventory(ROOT, sources)
    result["source_sha256_after"] = after
    if before != after and result["status"].startswith("PASS_"):
        result["status"] = "FAILED_CLOSED"
        result["error"] = "A source dependency changed during validation"
    result["artifact_sha256"] = {
        str(path.relative_to(ROOT)).replace("/", "\\"): sha(path)
        for folder in (build, evidence)
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name != "result.json"
    }
    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n",
                                          encoding="utf-8")
    print(json.dumps({"status": result["status"],
                      "report": str(evidence / "result.json"),
                      "error": result.get("error")}), flush=True)
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
