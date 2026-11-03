"""Host fixture generation and gated XSim/OOC validation for SITES=8/12.

The private scaling core remains unchanged.  Default execution is host-only;
the vendor flow is available only when an operator explicitly supplies both
--run-vendor and --vendor-slot-released after the root task grants a slot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = "20261022T131845Z_15a161"
CORE = ROOT / "deployment/hardware/z100_2026/window_mac_v1/z100_window_mac.sv"
TB = ROOT / "deployment/hardware/z100_2026/window_mac_scale_v1/tb_z100_window_mac_scale.sv"
PACKAGE_DIR = ROOT / f"deployment/candidates/pin640/provisional_models/{RUN_ROOT}/pipeline/package"
PACKAGE = PACKAGE_DIR / "MODEL.V8P"
GENERATED_HEADER = PACKAGE_DIR / "v8_generated_model.h"
GRAPH = ROOT / f"deployment/candidates/pin640/provisional_models/{RUN_ROOT}/pipeline/model/graph.json"
PARITY_DIR = ROOT / f"validation/board_z100/pin640_provisional/{RUN_ROOT}/host_parity/attempt_02"
RGB_INPUT = PARITY_DIR / "input_rgb.bin"
NCHW_INPUT = PARITY_DIR / "input_nchw_int8.bin"
PARITY_RESULT = PARITY_DIR / "result.json"
NATIVE_DIR = ROOT / "deployment/build/z100_native_window_weights/20261023T163945.127217Z_2b86c9ef"
NATIVE_MANIFEST = NATIVE_DIR / "manifest.json"
NATIVE_WEIGHTS = NATIVE_DIR / "weights_group4x32.bin"
NATIVE_BIASES = NATIVE_DIR / "biases_int32x32.bin"
EXPECTED = {
    PACKAGE: "96211aa416da6b23955a8b62cca594275daaa4db3e3954632960707c0ec0d44f",
    GENERATED_HEADER: "eb01437b8a70254472c6b06f4798b378644d61789aa72fd516c4c329dea953b5",
    GRAPH: "6ad39858999c9d7bc57b44887ad487f38a1a678d32e887a1c5c89fdcdd34e0b8",
    RGB_INPUT: "f82d6ce4ad170ec4859a49f405d6a0b7ca2cdbd93b5e57142a556a92ccd750e0",
    NCHW_INPUT: "0d458d68cf3e419e238245193cd5415c75b2931eb011a695c7b5a5765a1718b6",
    NATIVE_MANIFEST: "081aff4a32bc27123863ebf0d44d543d2561feffcd72e378233c974597f6a3e5",
    NATIVE_WEIGHTS: "9232bf379643e06e966c2a89aee0de854eca25a1f9d6872ff391ed3e44eb91a2",
    NATIVE_BIASES: "e228de7b7d9641d0b29d42e512477b19e44bbfe6d1f49c2c8d5b3e2bd0e36ff2",
}
EXPECTED_PARITY = {
    "package_sha256": EXPECTED[PACKAGE],
    "generated_header_sha256": EXPECTED[GENERATED_HEADER],
    "input_qspec_scale": 1.0 / 127.0,
    "rgb_sha256": EXPECTED[RGB_INPUT],
    "nchw_sha256": EXPECTED[NCHW_INPUT],
    "bytes": 1_228_800,
}
PIXELS = ((0, 0), (0, 319), (1, 1), (1, 318), (159, 160), (160, 159),
          (318, 318), (319, 319), (319, 0), (0, 160), (160, 0), (250, 257))
PART = "xc7z100ffg900-2"
VIVADO_BIN = Path("C:/appload/2026.1/Vivado/bin")
MAX_THREADS = 2
HEADER_NODE_RE = re.compile(r"^\s*(\{\.op=[^\n]+)", re.MULTILINE)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha(path.read_bytes())


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def source_paths() -> tuple[Path, ...]:
    return (CORE, TB, Path(__file__).resolve(), PACKAGE, GENERATED_HEADER, GRAPH,
            RGB_INPUT, NCHW_INPUT, PARITY_RESULT, NATIVE_MANIFEST, NATIVE_WEIGHTS, NATIVE_BIASES)


def parse_descriptor(line: str) -> dict[str, int | str | list[int]]:
    result: dict[str, int | str | list[int]] = {}
    inputs = re.search(r"\.inputs=\{([^}]*)\}", line)
    if inputs is None:
        raise ValueError("Generated descriptor has no braced input list")
    for name, value in re.findall(r"\.(\w+)=([^,}]+)", line):
        if name == "inputs":
            continue
        if name == "scale":
            result[name] = value
        else:
            result[name] = int(value)
    result["inputs"] = [int(value.strip()) for value in inputs.group(1).split(",") if value.strip()]
    required = {"op", "c", "h", "w", "kernel", "stride", "padding", "groups",
                "weight", "bias", "inputs"}
    if not required <= result.keys():
        raise ValueError(f"First generated descriptor lacks fields: {sorted(required - result.keys())}")
    return result


def signed_i8(value: int) -> int:
    return value - 256 if value >= 128 else value


def signed_i32(value: int) -> int:
    return value - (1 << 32) if value & 0x80000000 else value


def validate_model_inputs() -> dict:
    for path, expected in EXPECTED.items():
        actual = sha_file(path)
        if actual != expected:
            raise ValueError(f"Frozen input identity mismatch for {rel(path)}: {actual}")

    parity = json.loads(PARITY_RESULT.read_text(encoding="utf-8"))
    image = parity.get("image", {})
    if parity.get("status") != "PASS" or parity.get("test_predictions_performed") is not False or \
       parity.get("accuracy_evaluated") is not False or parity.get("physical_board_tested") is not False:
        raise ValueError("Pinned host parity record is not the expected host-only result")
    if (parity.get("package_sha256") != EXPECTED_PARITY["package_sha256"] or
        parity.get("generated_header_sha256") != EXPECTED_PARITY["generated_header_sha256"] or
        image.get("rgb_payload_sha256") != EXPECTED_PARITY["rgb_sha256"] or
        image.get("quantized_nchw_input_sha256") != EXPECTED_PARITY["nchw_sha256"] or
        image.get("rgb_payload_bytes") != EXPECTED_PARITY["bytes"] or
        image.get("quantized_nchw_input_bytes") != EXPECTED_PARITY["bytes"] or
        parity.get("input_qspec_scale") != EXPECTED_PARITY["input_qspec_scale"]):
        raise ValueError("Pinned host parity record does not bind the expected RGB/NCHW inputs")
    package_blob = PACKAGE.read_bytes()
    if len(package_blob) < 32:
        raise ValueError("V8PK package header is truncated")
    magic, version, payload_bytes, crc, node_count, arena_bytes, classes, input_size = struct.unpack(
        "<4s7I", package_blob[:32])
    payload = package_blob[32:]
    if (magic, version, payload_bytes, node_count, arena_bytes, classes, input_size) != \
       (b"V8PK", 1, 3_081_600, 163, 3_276_800, 9, 640) or len(payload) != payload_bytes or \
       (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
        raise ValueError("V8PK size, identity, or payload CRC differs from the frozen PIN640 package")

    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    if graph.get("format") != "V8GRAPH" or graph.get("input_shape") != [1, 3, 640, 640]:
        raise ValueError("Current graph input contract differs")
    nodes = graph.get("nodes", [])
    if len(nodes) != 163 or not nodes or nodes[0].get("id") != 0 or nodes[0].get("op") != "conv":
        raise ValueError("First graph node is not the expected first convolution")
    node = nodes[0]
    params = node.get("params", {})
    if (node.get("inputs") != [-1] or node.get("shape") != [1, 16, 320, 320] or
        params.get("stride") != [2, 2] or params.get("padding") != [1, 1] or
        params.get("dilation") != [1, 1] or params.get("groups") != 1):
        raise ValueError("First convolution geometry differs from the frozen graph")

    header_text = GENERATED_HEADER.read_text(encoding="utf-8")
    declared = re.search(r"static const V8Node v8_nodes\[(\d+)\]", header_text)
    descriptors = HEADER_NODE_RE.findall(header_text)
    if not declared or int(declared.group(1)) != 163 or len(descriptors) != 163:
        raise ValueError("Generated model header does not contain 163 node descriptors")
    parsed_descriptors = [parse_descriptor(line) for line in descriptors]
    op_codes = {"conv": 0, "silu": 1, "slice": 2, "concat": 3,
                "add": 4, "maxpool": 5, "upsample": 6}
    conv_geometry_checks = 0
    for index, (graph_node, header_node) in enumerate(zip(nodes, parsed_descriptors)):
        if graph_node.get("id") != index:
            raise ValueError(f"Graph node ordering/id differs at descriptor {index}")
        op = graph_node.get("op")
        shape = graph_node.get("shape")
        if op not in op_codes or not isinstance(shape, list) or len(shape) != 4:
            raise ValueError(f"Graph node {index} has an unsupported op or shape")
        if (header_node["op"], header_node["c"], header_node["h"], header_node["w"]) != \
           (op_codes[op], shape[1], shape[2], shape[3]):
            raise ValueError(f"Generated op/C/H/W differs from graph node {index}")
        if header_node["inputs"] != graph_node.get("inputs"):
            raise ValueError(f"Generated input references differ from graph node {index}")
        if op == "conv":
            params = graph_node.get("params", {})
            source_index = graph_node["inputs"][0]
            source_shape = graph["input_shape"] if source_index == -1 else nodes[source_index]["shape"]
            groups = params.get("groups")
            kernel = header_node["kernel"]
            if (not isinstance(groups, int) or groups <= 0 or source_shape[1] % groups or
                shape[1] % groups or kernel <= 0 or
                header_node["groups"] != groups or
                header_node["stride"] != params.get("stride", [None])[0] or
                header_node["padding"] != params.get("padding", [None])[0]):
                raise ValueError(f"Generated convolution geometry differs from graph node {index}")
            weight_bytes = shape[1] * (source_shape[1] // groups) * kernel * kernel
            bias_bytes = shape[1] * 4
            if (header_node["weight"] < 0 or header_node["weight"] + weight_bytes > len(payload) or
                header_node["bias"] < 0 or header_node["bias"] + bias_bytes > len(payload)):
                raise ValueError(f"Generated convolution parameter offsets exceed package at node {index}")
            conv_geometry_checks += 1
    if parsed_descriptors[0]["inputs"] != [-1]:
        raise ValueError("Generated first-convolution input reference is not the graph input")
    desc = parsed_descriptors[0]
    if (desc["op"], desc["c"], desc["h"], desc["w"], desc["kernel"],
        desc["stride"], desc["padding"], desc["groups"], desc["weight"], desc["bias"]) != \
       (0, 16, 320, 320, 3, 2, 1, 1, 0, 432):
        raise ValueError("Generated first-convolution descriptor changed")
    if len(payload) < 432 + 16 * 4 or 16 * 3 * 3 * 3 > len(payload) - desc["weight"]:
        raise ValueError("First convolution OIHW/bias ranges exceed package payload")
    return {"payload": payload, "descriptor": desc, "input_shape": [1, 3, 640, 640],
            "output_shape": node["shape"], "stride": 2, "padding": 1, "kernel": 3,
            "rgb_sha256": sha_file(RGB_INPUT), "nchw_sha256": sha_file(NCHW_INPUT),
            "parity_result_sha256": sha_file(PARITY_RESULT), "package_crc32": f"{crc:08x}",
            "generated_header_graph_crosscheck": {"descriptors_parsed": len(parsed_descriptors),
                                                   "op_c_h_w_matches": len(parsed_descriptors),
                                                   "inputs_match": len(parsed_descriptors),
                                                   "convolution_parameter_ranges_checked": conv_geometry_checks,
                                                   "firstconv_inputs": desc["inputs"]}}


def write_hex(path: Path, values: list[int], width: int) -> None:
    path.write_text("".join(f"{value & ((1 << (width * 4)) - 1):0{width}x}\n" for value in values),
                    encoding="ascii", newline="\n")


def create_firstconv_fixture(build: Path, model: dict) -> dict:
    fixture = build / "fixture"
    fixture.mkdir(parents=True, exist_ok=False)
    payload: bytes = model["payload"]
    desc: dict = model["descriptor"]
    weight_origin, bias_origin = int(desc["weight"]), int(desc["bias"])
    nchw = NCHW_INPUT.read_bytes()
    if len(nchw) != 3 * 640 * 640:
        raise ValueError("Quantized NCHW input length differs from 3x640x640")
    input_planes = 640 * 640
    weights = [0] * (9 * 4 * 32)
    biases = [0] * 32
    for lane in range(16):
        biases[lane] = signed_i32(struct.unpack_from("<I", payload, bias_origin + lane * 4)[0])
    for group in range(9):
        channel_block, spatial = divmod(group, 9)
        ky, kx = divmod(spatial, 3)
        for tap in range(4):
            channel = channel_block * 4 + tap
            for lane in range(32):
                if channel < 3 and lane < 16:
                    oc = lane
                    offset = weight_origin + ((oc * 3 + channel) * 3 + ky) * 3 + kx
                    weights[(group * 4 + tap) * 32 + lane] = payload[offset]

    activations = [0] * (9 * 4 * 12)
    expected = [0] * (12 * 32)
    window_reports = []
    for site, (oy, ox) in enumerate(PIXELS):
        sums = [biases[lane] if lane < 16 else 0 for lane in range(32)]
        for cb in range(1):
            for ky in range(3):
                iy = oy * 2 + ky - 1
                for kx in range(3):
                    ix = ox * 2 + kx - 1
                    group = cb * 9 + ky * 3 + kx
                    for tap in range(4):
                        channel = cb * 4 + tap
                        value = 0
                        if channel < 3 and 0 <= iy < 640 and 0 <= ix < 640:
                            value = signed_i8(nchw[channel * input_planes + iy * 640 + ix])
                        activations[(group * 4 + tap) * 12 + site] = value & 0xff
                        for lane in range(16):
                            source_weight = payload[weight_origin + ((lane * 3 + channel) * 3 + ky) * 3 + kx] \
                                if channel < 3 else 0
                            sums[lane] += value * signed_i8(source_weight)
        for lane, value in enumerate(sums):
            if not -(1 << 31) <= value < (1 << 31):
                raise ValueError(f"Selected first-convolution reference leaves INT32 at site {site}, lane {lane}")
            if lane >= 16 and value != 0:
                raise ValueError("Padded first-convolution reference lane is nonzero")
            expected[site * 32 + lane] = value & 0xffffffff
        window_reports.append({"site": site, "output_y": oy, "output_x": ox,
                               "signed_raw_sums_int32_lanes0_15": sums[:16],
                               "padded_lanes16_31_zero": all(v == 0 for v in sums[16:])})

    write_hex(fixture / "firstconv_weights.hex", weights, 2)
    write_hex(fixture / "firstconv_bias.hex", [v & 0xffffffff for v in biases], 8)
    write_hex(fixture / "firstconv_activations.hex", activations, 2)
    write_hex(fixture / "firstconv_expected.hex", expected, 8)

    native_manifest = json.loads(NATIVE_MANIFEST.read_text(encoding="utf-8"))
    first_job = next((job for job in native_manifest.get("jobs", []) if job.get("node") == 0), None)
    native_weights = NATIVE_WEIGHTS.read_bytes()
    native_biases = NATIVE_BIASES.read_bytes()
    expected_packed_weights = bytes(weights)
    expected_packed_biases = b"".join(struct.pack("<i", v) for v in biases)
    if (first_job is None or first_job.get("groups") != 9 or first_job.get("output_lanes") != 16 or
        native_weights[:1152] != expected_packed_weights or native_biases[:128] != expected_packed_biases):
        raise ValueError("Independent OIHW fixture differs from the existing native firstconv asset")

    report = {"source": "direct original V8PK payload OIHW plus bias and current host-parity NCHW bytes",
              "source_package_sha256": sha_file(PACKAGE), "source_nchw_sha256": sha_file(NCHW_INPUT),
              "source_rgb_sha256": sha_file(RGB_INPUT), "node": 0,
              "input_shape": model["input_shape"], "output_shape": model["output_shape"],
              "kernel": 3, "stride": 2, "padding": 1, "groups": 1,
              "weight_offset_payload": weight_origin, "bias_offset_payload": bias_origin,
              "output_lanes": 16, "group_count": 9, "direct_windows": window_reports,
              "generated_fixture": {name: {"bytes": path.stat().st_size, "sha256": sha_file(path)}
                                    for name, path in sorted((p.name, p) for p in fixture.iterdir())},
              "crosscheck": {"native_manifest_sha256": sha_file(NATIVE_MANIFEST),
                             "first_job_node": first_job["node"],
                             "OIHW_reordered_weight_bytes_equal": True,
                             "OIHW_bias_bytes_equal": True}}
    return report


def braced(path: Path) -> str:
    value = path.resolve().as_posix()
    if "{" in value or "}" in value:
        raise ValueError(f"Tcl path contains braces: {value}")
    return "{" + value + "}"


def write_ooc_tcl(sites: int, evidence: Path, build: Path) -> Path:
    expected = 1024 if sites == 8 else 1536
    nonmult = 256 if sites == 8 else 384
    total = expected + nonmult
    path = evidence / f"synth_sites{sites}.tcl"
    script = f'''set_param general.maxThreads {MAX_THREADS}
if {{![string match 2026.1* [version -short]]}} {{error "Requires Vivado 2026.1"}}
read_verilog -sv {braced(CORE)}
synth_design -top z100_window_mac -part {PART} -mode out_of_context -flatten_hierarchy none -generic {{SITES={sites}}}
create_clock -name mac_clk -period 10.000 [get_ports clk]
report_utilization -file {braced(evidence / f"utilization_sites{sites}.rpt")}
report_utilization -hierarchical -file {braced(evidence / f"hierarchical_utilization_sites{sites}.rpt")}
report_timing_summary -delay_type min_max -report_unconstrained -file {braced(evidence / f"timing_unplaced_diagnostic_sites{sites}.rpt")}
write_checkpoint -force {braced(build / f"sites{sites}_post_synth.dcp")}
set lut [llength [get_cells -quiet -hier -filter {{REF_NAME =~ LUT*}}]]
set ff [llength [get_cells -quiet -hier -filter {{REF_NAME =~ FD*}}]]
set ram36cells [get_cells -quiet -hier -filter {{REF_NAME =~ RAMB36*}}]
set ram18cells [get_cells -quiet -hier -filter {{REF_NAME =~ RAMB18*}}]
set ram36 [llength $ram36cells]
set ram18 [llength $ram18cells]
set bram36eq [expr {{$ram36 + ($ram18 / 2.0)}}]
set dsps [get_cells -quiet -hier -filter {{REF_NAME =~ DSP*}}]
set dsp48 [get_cells -quiet -hier -filter {{REF_NAME == DSP48E1}}]
set latch [llength [get_cells -quiet -hier -filter {{REF_NAME =~ LD*}}]]
set blackboxes [get_cells -quiet -hier -filter {{IS_BLACKBOX == 1}}]
array set use_mult_counts {{}}
set census [open {braced(evidence / f"dsp48e1_sites{sites}.tsv")} w]
puts $census "cell\\tAREG\\tBREG\\tMREG\\tPREG\\tUSE_MULT\\tUSE_SIMD"
foreach cell $dsp48 {{
    set name [get_property NAME $cell]
    set values {{}}
    foreach property {{AREG BREG MREG PREG USE_MULT USE_SIMD}} {{
        set value [get_property -quiet $property $cell]
        if {{$value eq ""}} {{set value "UNAVAILABLE"}}
        lappend values $value
    }}
    set mode [string toupper [lindex $values 4]]
    if {{![info exists use_mult_counts($mode)]}} {{set use_mult_counts($mode) 0}}
    incr use_mult_counts($mode)
    puts $census "$name\\t[join $values \\t]"
}}
close $census
array set owner_count {{0 0 1 0 2 0 3 0}}
set unmatched 0
set memcensus [open {braced(evidence / f"bram_owner_sites{sites}.tsv")} w]
puts $memcensus "cell\\tprimitive\\tweight_bank"
foreach cell [concat $ram36cells $ram18cells] {{
    set name [get_property NAME $cell]
    set primitive [get_property REF_NAME $cell]
    if {{[regexp {{gen_weights\\[([0-3])\\]}} $name matched bank]}} {{
        incr owner_count($bank)
    }} else {{
        set bank "UNMATCHED"
        incr unmatched
    }}
    puts $memcensus "$name\\t$primitive\\t$bank"
}}
close $memcensus
set multiply 0
set none 0
set other 0
foreach mode [array names use_mult_counts] {{
    if {{$mode eq "MULTIPLY"}} {{set multiply $use_mult_counts($mode)}} elseif {{$mode eq "NONE"}} {{set none $use_mult_counts($mode)}} else {{incr other $use_mult_counts($mode)}}
}}
set owners [open {braced(evidence / f"bram_owners_sites{sites}.txt")} w]
for {{set bank 0}} {{$bank < 4}} {{incr bank}} {{puts $owners "bank$bank $owner_count($bank)"}}
puts $owners "unmatched $unmatched"
close $owners
set f [open {braced(evidence / f"observability_sites{sites}.txt")} w]
puts $f "DSP_TOTAL [llength $dsps]"
puts $f "DSP48E1_COUNT [llength $dsp48]"
puts $f "DSP_MULTIPLY_COUNT $multiply"
puts $f "DSP_NONE_COUNT $none"
puts $f "DSP_OTHER_MODE_COUNT $other"
puts $f "LUT_COUNT $lut"
puts $f "FF_COUNT $ff"
puts $f "RAMB36E1_COUNT $ram36"
puts $f "RAMB18E1_COUNT $ram18"
puts $f "BRAM36_EQ $bram36eq"
puts $f "LATCH_COUNT $latch"
puts $f "BLACKBOX_COUNT [llength $blackboxes]"
puts $f "BRAM_OWNER_UNMATCHED $unmatched"
for {{set bank 0}} {{$bank < 4}} {{incr bank}} {{puts $f "BRAM_OWNER_BANK$bank $owner_count($bank)"}}
close $f
puts "WINDOW_MAC_SCALE_SYNTH sites={sites} version=[version -short] part={PART} lut=$lut ff=$ff ram36=$ram36 ram18=$ram18 bram36eq=$bram36eq dsp_total=[llength $dsps] dsp48=[llength $dsp48] dsp_multiply=$multiply dsp_none=$none dsp_other=$other latches=$latch blackbox=[llength $blackboxes] bram_unmatched=$unmatched bank0=$owner_count(0) bank1=$owner_count(1) bank2=$owner_count(2) bank3=$owner_count(3)"
if {{$lut > 60000 || $ff > 35000 || $bram36eq < 28.0 || $bram36eq > 40.0 ||
     [llength $dsps] != {total} || [llength $dsp48] != {total} || $multiply != {expected} ||
     $none != {nonmult} || $other != 0 || $latch != 0 || [llength $blackboxes] != 0 ||
     $unmatched != 0 || $owner_count(0) == 0 || $owner_count(1) == 0 ||
     $owner_count(2) == 0 || $owner_count(3) == 0}} {{
    error "SITES={sites} failed fixed DSP/BRAM/logic component screen"
}}
exit
'''
    path.write_text(script, encoding="utf-8", newline="\n")
    return path


def run_logged(name: str, command: list[str], cwd: Path, env: dict[str, str], evidence: Path,
               result: dict) -> str:
    completed = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8",
                               errors="replace", stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, check=False)
    output = completed.stdout
    (evidence / f"{name}.log").write_text(output, encoding="utf-8", newline="\n")
    result["commands"].append({"name": name, "args": list(map(str, command)),
                               "return_code": completed.returncode, "cwd": str(cwd)})
    if completed.returncode != 0:
        raise RuntimeError(f"{name} returned {completed.returncode}")
    return output


def check_simulation(output: str) -> dict:
    matches = re.findall(r"WINDOW_MAC_SCALE_PASS\s+([^\r\n]+)", output)
    if len(matches) != 1 or re.search(r"(?:Fatal:|FATAL:)", output):
        raise ValueError("Combined XSim did not emit exactly one successful coverage marker")
    values = {name: int(value) for name, value in re.findall(r"([a-zA-Z0-9_]+)=(\d+)", matches[0])}
    expected = {
        "sites8_jobs": 66, "sites8_words": 9216, "sites8_metadata": 288,
        "sites8_stream_errors": 3, "sites8_config_errors": 6, "sites8_run_errors": 6,
        "sites8_cross": 512, "sites8_saturation": 512, "sites8_cancel_offsets": 5,
        "sites8_reset_offsets": 5, "sites8_real_windows": 16, "sites8_site_tail_mask": 31,
        "sites8_lane_tail_mask": 15, "sites8_group_mask": 31,
        "sites12_jobs": 86, "sites12_words": 17344, "sites12_metadata": 542,
        "sites12_stream_errors": 3, "sites12_config_errors": 6, "sites12_run_errors": 6,
        "sites12_cross": 768, "sites12_saturation": 768, "sites12_cancel_offsets": 5,
        "sites12_reset_offsets": 5, "sites12_real_windows": 24, "sites12_site_tail_mask": 127,
        "sites12_lane_tail_mask": 15, "sites12_group_mask": 31, "max_groups": 1024,
    }
    for name, want in expected.items():
        if values.get(name) != want:
            raise ValueError(f"XSim coverage {name}={values.get(name)!r}; expected {want}")
    for name in ("sites8_stalls", "sites8_bubbles", "sites12_stalls", "sites12_bubbles"):
        if values.get(name, 0) <= 0:
            raise ValueError(f"XSim omitted required {name} coverage")
    if values["sites8_words"] != values["sites8_metadata"] * 32 or \
       values["sites12_words"] != values["sites12_metadata"] * 32:
        raise ValueError("XSim output-word count does not cover all 32 lanes for each site")
    return {"status": "PASS", "coverage": values,
            "golden": "independent signed 64-bit Python direct arithmetic plus frozen current OIHW first-convolution package bytes",
            "checked": ["every lane result and overflow bit", "inactive lane zero fill",
                        "token/site/lanes/last metadata", "output stability under stalls",
                        "all required site/lane/group tails", "reused resident weights across runs",
                        "INT32 transient overflow recovery and final saturation", "invalid config/run/stream rejection",
                        "in-flight reload admission", "cancel/reset at five pipeline offsets and recovery",
                        "current first-convolution selected windows under SITES=8 and SITES=12"]}


def parse_ooc(output: str, evidence: Path, sites: int) -> dict:
    match = re.findall(
        rf"WINDOW_MAC_SCALE_SYNTH sites={sites} version=(\S+) part=(\S+) lut=(\d+) ff=(\d+) "
        rf"ram36=(\d+) ram18=(\d+) bram36eq=([0-9.]+) dsp_total=(\d+) dsp48=(\d+) "
        rf"dsp_multiply=(\d+) dsp_none=(\d+) dsp_other=(\d+) latches=(\d+) blackbox=(\d+) "
        rf"bram_unmatched=(\d+) bank0=(\d+) bank1=(\d+) bank2=(\d+) bank3=(\d+)", output)
    if len(match) != 1:
        raise ValueError(f"Vivado SITES={sites} did not produce exactly one resource marker")
    names = ("vivado_version", "part", "lut", "ff", "ram36", "ram18", "bram36_equivalent",
             "dsp_total", "dsp48e1", "dsp_multiply", "dsp_none", "dsp_other_modes",
             "latches", "blackboxes", "bram_owner_unmatched", "bram_owner_bank0",
             "bram_owner_bank1", "bram_owner_bank2", "bram_owner_bank3")
    raw = dict(zip(names, match[0]))
    data = {k: (float(v) if k == "bram36_equivalent" else
                v if k in ("vivado_version", "part") else int(v)) for k, v in raw.items()}
    expected_multiply = 1024 if sites == 8 else 1536
    expected_none = 256 if sites == 8 else 384
    expected_total = expected_multiply + expected_none
    if not data["vivado_version"].startswith("2026.1") or data["part"] != PART:
        raise ValueError(f"Vivado SITES={sites} used an unexpected tool version or target")
    if (data["dsp_total"], data["dsp48e1"], data["dsp_multiply"], data["dsp_none"],
        data["dsp_other_modes"]) != (expected_total, expected_total, expected_multiply, expected_none, 0):
        raise ValueError(f"Vivado SITES={sites} primitive or USE_MULT census differs from fixed gate")
    if not 28.0 <= data["bram36_equivalent"] <= 40.0:
        raise ValueError(f"Vivado SITES={sites} shared BRAM36-equivalent count outside 28..40")
    if data["lut"] > 60000 or data["ff"] > 35000 or data["latches"] != 0 or data["blackboxes"] != 0:
        raise ValueError(f"Vivado SITES={sites} logic/latch/blackbox screen failed")
    if data["bram_owner_unmatched"] != 0 or any(data[f"bram_owner_bank{i}"] <= 0 for i in range(4)):
        raise ValueError(f"Vivado SITES={sites} BRAM cells do not reconcile to all four generated weight banks")
    bram_cells = (evidence / f"bram_owner_sites{sites}.tsv").read_text(
        encoding="utf-8", errors="replace").splitlines()
    owner_total = sum(data[f"bram_owner_bank{i}"] for i in range(4))
    if len(bram_cells) != data["ram36"] + data["ram18"] + 1 or \
       owner_total != data["ram36"] + data["ram18"]:
        raise ValueError(f"Vivado SITES={sites} detailed BRAM cell/owner totals do not reconcile")
    if any(len(row.split("\t")) != 3 or row.split("\t")[2] not in
           ("weight_bank", "0", "1", "2", "3") for row in bram_cells):
        raise ValueError(f"Vivado SITES={sites} detailed BRAM owner census has an unmatched row")
    for name in (f"dsp48e1_sites{sites}.tsv", f"bram_owner_sites{sites}.tsv",
                 f"bram_owners_sites{sites}.txt", f"observability_sites{sites}.txt",
                 f"utilization_sites{sites}.rpt", f"hierarchical_utilization_sites{sites}.rpt",
                 f"timing_unplaced_diagnostic_sites{sites}.rpt"):
        if not (evidence / name).is_file():
            raise ValueError(f"Vivado SITES={sites} is missing report {name}")
    cells = (evidence / f"dsp48e1_sites{sites}.tsv").read_text(encoding="utf-8", errors="replace").splitlines()
    if len(cells) != expected_total + 1:
        raise ValueError(f"Vivado SITES={sites} detailed DSP cell list has {len(cells)-1}, expected {expected_total}")
    modes = {}
    for line in cells[1:]:
        fields = line.split("\t")
        if len(fields) != 7:
            raise ValueError(f"Vivado SITES={sites} malformed DSP census row")
        modes[fields[5]] = modes.get(fields[5], 0) + 1
    if modes != {"MULTIPLY": expected_multiply, "NONE": expected_none}:
        raise ValueError(f"Vivado SITES={sites} detailed DSP mode rows disagree: {modes}")
    data["status"] = "PASS_OOC_UNPLACED_COMPONENT_SCREEN"
    data["clock_period_ns"] = 10.0
    data["clock_note"] = "100 MHz create_clock used only for unplaced diagnostic timing; no frequency acceptance and no external IO delays"
    data["dsp_use_mult_modes"] = modes
    data["detailed_bram_owner_counts"] = {f"bank{i}": data[f"bram_owner_bank{i}"] for i in range(4)}
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-vendor", action="store_true", help="run combined XSim and both OOC screens")
    parser.add_argument("--vendor-slot-released", action="store_true",
                        help="required explicit confirmation that root released a vendor slot")
    args = parser.parse_args()
    if args.run_vendor != args.vendor_slot_released:
        parser.error("--run-vendor and --vendor-slot-released must be supplied together")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    evidence = ROOT / "validation/board_z100/window_mac_scale_v1" / run_id
    build = ROOT / "deployment/build/z100_window_mac_scale_v1" / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    sources = source_paths()
    before = {rel(path): sha_file(path) for path in sources}
    if before[rel(CORE)] != "c2de472f539276da097e5ccd5bc7d44f2695dbff55ecb73458ea0105accbb643":
        raise ValueError("Frozen window_mac_v1 RTL identity differs")
    snapshot = evidence / "source_snapshot"
    for path in sources:
        destination = snapshot / rel(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)

    result = {
        "schema": "z100-window-mac-scale/1", "status": "RUNNING", "run_id": run_id,
        "scope": "Private SITES=8/12 correctness and OOC component screen; no route, integration, board, or FPS claim",
        "source_sha256_before": before, "source_snapshot": str(snapshot),
        "source_sha256_expected_core": before[rel(CORE)], "device_part": PART,
        "limits": {"sites8_dsp_multiply": 1024, "sites8_dsp_none": 256, "sites8_dsp_total": 1280,
                   "sites12_dsp_multiply": 1536, "sites12_dsp_none": 384, "sites12_dsp_total": 1920,
                   "shared_bram36_equivalent": [28, 40], "lut_max": 60000, "ff_max": 35000,
                   "latches": 0, "blackboxes": 0},
        "toolchain": {"python": sys.executable, "vivado_bin": str(VIVADO_BIN),
                      "max_vendor_threads": MAX_THREADS, "numerical_threads": 1},
        "board_access": False, "production_integrated": False, "route_attempted": False,
        "bitstream_created": False, "vendor_attempted": False, "commands": [],
    }
    try:
        model = validate_model_inputs()
        result["model_identity"] = {k: v for k, v in model.items() if k != "payload"}
        result["firstconv_fixture"] = create_firstconv_fixture(build, model)
        result["host_preflight"] = {"status": "PASS_HOST_FIXTURE_ONLY",
                                    "direct_windows_per_mode": len(PIXELS),
                                    "oi_hw_golden": True, "native_pack_crosscheck": True,
                                    "input_bytes": EXPECTED_PARITY["bytes"]}

        if args.run_vendor:
            bindir = VIVADO_BIN
            for tool in ("xvlog.bat", "xelab.bat", "xsim.bat", "vivado.bat"):
                if not (bindir / tool).is_file():
                    raise FileNotFoundError(f"Missing Vivado 2026.1 tool: {bindir / tool}")
            env = dict(os.environ)
            for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                        "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS"):
                env[key] = "1"
            result["vendor_attempted"] = True
            xvlog = run_logged("xvlog_combined", [str(bindir / "xvlog.bat"), "-sv", str(CORE), str(TB)],
                               build, env, evidence, result)
            if "overflow of 32-bit signed integer" in xvlog.lower():
                raise ValueError("XSim compiler diagnosed an overflowing 32-bit signed testbench constant")
            run_logged("xelab_combined", [str(bindir / "xelab.bat"), "-mt", str(MAX_THREADS),
                                          "tb_z100_window_mac_scale", "-s", "window_mac_scale_sim"],
                       build, env, evidence, result)
            sim = run_logged("xsim_combined", [str(bindir / "xsim.bat"), "window_mac_scale_sim", "-runall"],
                             build, env, evidence, result)
            result["simulation"] = check_simulation(sim)

            result["synthesis"] = {}
            for sites in (8, 12):
                tcl = write_ooc_tcl(sites, evidence, build)
                synth = run_logged(f"vivado_ooc_sites{sites}",
                    [str(bindir / "vivado.bat"), "-mode", "batch", "-log",
                     str(evidence / f"vivado_sites{sites}.log"), "-journal",
                     str(evidence / f"vivado_sites{sites}.jou"), "-source", str(tcl)],
                    build, env, evidence, result)
                result["synthesis"][str(sites)] = parse_ooc(synth, evidence, sites)
            result["status"] = "PASS_XSIM_AND_OOC_COMPONENT_SCREENS_ONLY"
        else:
            result["status"] = "PASS_HOST_FIXTURE_ONLY_VENDOR_PENDING"
            result["vendor_status"] = "NOT_RUN_NO_EXPLICIT_SLOT_RELEASE"
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["error"] = f"{type(exc).__name__}: {exc}"

    after = {rel(path): sha_file(path) for path in sources if path.is_file()}
    result["source_sha256_after"] = after
    if after != before:
        result["status"] = "FAILED_CLOSED"
        result["error"] = "A frozen source or dependency changed during validation"
    result["source_hashes_unchanged"] = after == before
    artifacts = {}
    for folder in (evidence, build):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path != evidence / "result.json":
                artifacts[rel(path)] = sha_file(path)
    result["artifact_sha256"] = artifacts
    report = evidence / "result.json"
    report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "report": str(report),
                      "error": result.get("error"), "vendor_attempted": result["vendor_attempted"]}), flush=True)
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
