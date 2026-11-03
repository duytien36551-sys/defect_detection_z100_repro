"""Host-bind v1 simulation evidence and synthesize the attribute-only v2 packer.

Run --preflight-only first. --run-synth repeats those immutable-source checks
and performs exactly one Vivado2026.1 out-of-context synthesis; it does not run
simulation, implementation, routing, or board operations.
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

ROOT = Path(__file__).resolve().parents[1]
V1_DIR = ROOT / "deployment/hardware/z100_2026/native_output_packer_v1"
V2_DIR = ROOT / "deployment/hardware/z100_2026/native_output_packer_v2"
V1_RTL = V1_DIR / "z100_native_output_packer.sv"
V1_TB = V1_DIR / "tb_z100_native_output_packer.sv"
V1_VALIDATOR = ROOT / "tools/validate_z100_native_output_packer.py"
V1_RUN = "20261023T180938.310814Z_1326831c"
V1_REPORT = ROOT / f"validation/board_z100/native_output_packer_v1/{V1_RUN}/result.json"
V1_XSIM_LOG = ROOT / f"validation/board_z100/native_output_packer_v1/{V1_RUN}/xsim.log"
V1_BUILD = ROOT / f"deployment/build/z100_native_output_packer_v1/{V1_RUN}"
V2_RTL = V2_DIR / "z100_native_output_packer.sv"
VIVADO = Path("C:/appload/2026.1/Vivado/bin/vivado.bat")
EXPECTED_V1_RTL_SHA256 = "22411eb93397de3d5f278335e5626b995567f3cb9f9a9c0cb86dd3464e656994"
EXPECTED_V1_TB_SHA256 = "7d8876f184f7bfec0859e6cd558764c94a684fba3abd3b160a9334241fec311c"
EXPECTED_V1_VALIDATOR_SHA256 = "9c5718ccdfa0fe6fff940475fef844f42fa6c6b606d0016303896ffa99b7eaae"
EXPECTED_V1_REPORT_SHA256 = "35131d43a8bbc0618f1c481400084306e039529c91a257970d1ecc260a4bb765"
ATTRIBUTE = b'(* use_dsp="no" *)\n'
MODULE_DECL = b"module z100_native_output_packer #("
FIXTURE_NAMES = ("native_output_cases.hex", "native_output_counts.svh",
                 "native_output_expected.hex", "native_output_input.hex",
                 "native_output_offsets.hex")
EXPECTED_SIMULATION = {
    "status": "PASS", "cases": 67, "input_beats": 15430,
    "expected_input_beats": 15430, "output_words": 5323, "done_count": 67,
    "input_bubble_cycles": 62, "input_stall_cycles": 221,
    "input_stability_checks": 221, "output_stall_cycles": 23,
    "output_stability_checks": 22, "two_buffer_full_checks": 3,
    "busy_configuration_reload_checks": 3, "max_consecutive_input_beats": 251,
    "max_consecutive_output_words": 48, "bad_configurations_rejected": 4,
    "bad_input_metadata_rejected": 5, "reset_abort_recovery_cases": 1,
    "cancel_abort_recovery_cases": 2, "sites_parameter_instances": [4, 8, 12],
}
EXPECTED_V1_SYNTH = {"lut": 3771, "ff": 8439, "ram36": 0, "ram18": 0,
                     "bram36_equivalent": 0.0, "dsp": 4, "latch": 0,
                     "blackbox": 0}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("/", "\\")


def v1_source_paths(v1_report: dict) -> tuple[Path, ...]:
    paths = []
    for rel, expected in v1_report["source_sha256_before"].items():
        path = ROOT / Path(rel.replace("\\", "/"))
        if not path.is_file() or sha_file(path) != expected:
            raise ValueError(f"v1 frozen dependency is missing or changed: {rel}")
        paths.append(path)
    return tuple(paths)


def check_preflight():
    for path, expected in ((V1_RTL, EXPECTED_V1_RTL_SHA256),
                           (V1_TB, EXPECTED_V1_TB_SHA256),
                           (V1_VALIDATOR, EXPECTED_V1_VALIDATOR_SHA256),
                           (V1_REPORT, EXPECTED_V1_REPORT_SHA256)):
        if sha_file(path) != expected:
            raise ValueError(f"Pinned v1 source/report hash mismatch: {relative(path)}")
    v1_report = json.loads(V1_REPORT.read_text(encoding="utf-8"))
    if v1_report.get("simulation") != EXPECTED_SIMULATION:
        raise ValueError("v1 XSim numeric coverage differs from the accepted 67-case result")
    v1_synthesis = v1_report.get("synthesis", {})
    if v1_synthesis.get("status") != "FAIL_SCREEN" or any(
        v1_synthesis.get(key) != value for key, value in EXPECTED_V1_SYNTH.items()
    ):
        raise ValueError("v1 OOC baseline resource census differs from its frozen report")
    log = V1_XSIM_LOG.read_text(encoding="utf-8", errors="replace")
    if "NATIVE_OUTPUT_PACKER_PASS cases=67 inputs=15430 outputs=5323 done=67" not in log:
        raise ValueError("Pinned v1 XSim transcript does not contain the exact 67-case PASS")

    fixture_paths = tuple(V1_BUILD / name for name in FIXTURE_NAMES)
    report_artifacts = v1_report["artifact_sha256"]
    for path in fixture_paths:
        key = relative(path)
        expected = report_artifacts.get(key)
        if not expected or sha_file(path) != expected:
            raise ValueError(f"v1 simulation fixture differs from immutable report: {key}")

    v1_bytes = V1_RTL.read_bytes()
    v2_bytes = V2_RTL.read_bytes()
    if v1_bytes.count(MODULE_DECL) != 1:
        raise ValueError("v1 packer module declaration count changed")
    expected_v2 = v1_bytes.replace(MODULE_DECL, ATTRIBUTE + MODULE_DECL, 1)
    if v2_bytes != expected_v2:
        raise ValueError("v2 RTL must differ from v1 only by the requested module attribute")
    if v2_bytes.count(ATTRIBUTE + MODULE_DECL) != 1:
        raise ValueError("v2 module-level use_dsp attribute is absent or duplicated")

    sources = tuple(dict.fromkeys((V1_RTL, V1_TB, V1_VALIDATOR, V1_REPORT,
                                   V1_XSIM_LOG, *fixture_paths, V2_RTL,
                                   Path(__file__), *v1_source_paths(v1_report))))
    hashes = {relative(path): sha_file(path) for path in sources}
    return {"status": "PASS", "v1_report": relative(V1_REPORT),
            "v1_report_sha256": sha_file(V1_REPORT),
            "v1_xsim_log_sha256": sha_file(V1_XSIM_LOG),
            "v1_simulation": v1_report["simulation"],
            "v1_synthesis_baseline": v1_report["synthesis"],
            "v1_fixture_sha256": {relative(path): sha_file(path) for path in fixture_paths},
            "v1_rtl_sha256": sha_file(V1_RTL),
            "v2_rtl_sha256": sha_file(V2_RTL),
            "v2_rtl_bytes_equal_v1_plus_one_module_attribute": True,
            "attribute": '(* use_dsp="no" *)',
            "dependencies_sha256_before": hashes,
            "source_paths": sources}


def source_inventory(paths: tuple[Path, ...]):
    return {relative(path): sha_file(path) for path in paths}


def snapshot(paths: tuple[Path, ...], folder: Path):
    folder.mkdir(parents=True, exist_ok=False)
    for path in paths:
        # Prefix the basename with its digest so distinct frozen result.json
        # dependencies remain unambiguous in a flat source snapshot.
        target = folder / f"{sha_file(path)[:12]}_{path.name}"
        if target.exists():
            raise ValueError(f"Snapshot basename collision: {path.name}")
        shutil.copy2(path, target)


def run_synthesis(build: Path, evidence: Path, env: dict[str, str], result: dict):
    if not VIVADO.is_file():
        raise FileNotFoundError(f"Vivado2026.1 is missing: {VIVADO}")
    tcl = build / "synth.tcl"
    tcl.write_text("""set_param general.maxThreads 2
if {![string match 2026.1* [version -short]]} {error "Requires Vivado2026.1"}
read_verilog -sv {%s}
synth_design -top z100_native_output_packer -part xc7z100ffg900-2 -mode out_of_context -flatten_hierarchy none
report_utilization -file {%s}
report_utilization -hierarchical -file {%s}
write_checkpoint -force {%s}
set lut_cells [llength [get_cells -hier -filter {REF_NAME =~ LUT*}]]
set ff_cells [llength [get_cells -hier -filter {REF_NAME =~ FD*}]]
set ram36 [llength [get_cells -hier -filter {REF_NAME =~ RAMB36*}]]
set ram18 [llength [get_cells -hier -filter {REF_NAME =~ RAMB18*}]]
set dsp_cells [get_cells -hier -filter {REF_NAME =~ DSP*}]
set dsp_count [llength $dsp_cells]
set latch_count [llength [get_cells -hier -filter {REF_NAME =~ LD*}]]
set blackbox_count [llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]
puts "NATIVE_OUTPUT_PACKER_V2_SYNTH lut_cells=$lut_cells ff_cells=$ff_cells ram36=$ram36 ram18=$ram18 dsp=$dsp_count latch=$latch_count blackbox=$blackbox_count"
foreach cell $dsp_cells {
    puts "NATIVE_OUTPUT_PACKER_V2_DSP_CELL name=[get_property NAME $cell] ref=[get_property REF_NAME $cell]"
}
exit
""" % tuple(path.as_posix() for path in (V2_RTL, evidence / "utilization.rpt",
            evidence / "utilization_hierarchical.rpt", build / "post_synth.dcp")),
        encoding="utf-8")
    command = [str(VIVADO), "-mode", "batch", "-log", str(evidence / "vivado.log"),
               "-journal", str(evidence / "vivado.jou"), "-source", str(tcl)]
    process = subprocess.run(command, cwd=build, env=env, text=True,
                             encoding="utf-8", errors="replace",
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (evidence / "synth.log").write_text(process.stdout, encoding="utf-8")
    result["commands"].append({"name": "vivado_ooc_synthesis", "argv": command,
                               "cwd": str(build), "return_code": process.returncode})
    if process.returncode:
        raise RuntimeError(f"Vivado synthesis returned {process.returncode}")
    if "Vivado v2026.1" not in process.stdout and "Vivado2026.1" not in process.stdout:
        raise ValueError("Vivado2026.1 version banner was absent")

    marker = re.search(
        r"NATIVE_OUTPUT_PACKER_V2_SYNTH lut_cells=(\d+) ff_cells=(\d+) "
        r"ram36=(\d+) ram18=(\d+) dsp=(\d+) latch=(\d+) blackbox=(\d+)",
        process.stdout)
    if not marker:
        raise ValueError("OOC primitive resource census marker missing")
    lut_cells, ff_cells, ram36, ram18, dsp, latch, blackbox = map(int, marker.groups())
    report = (evidence / "utilization.rpt").read_text(encoding="utf-8", errors="replace")
    slice_lut_match = re.search(r"^\|\s*Slice LUTs\*?\s*\|\s*(\d+)\s*\|", report, re.MULTILINE)
    lut_logic_match = re.search(r"^\|\s*LUT as Logic\s*\|\s*(\d+)\s*\|", report, re.MULTILINE)
    lut_memory_match = re.search(r"^\|\s*LUT as Memory\s*\|\s*(\d+)\s*\|", report, re.MULTILINE)
    slice_ff_match = re.search(r"^\|\s*Slice Registers\s*\|\s*(\d+)\s*\|", report, re.MULTILINE)
    if not all((slice_lut_match, lut_logic_match, lut_memory_match, slice_ff_match)):
        raise ValueError("Vivado Slice LUT/register utilization rows are missing")
    slice_luts, lut_as_logic, lut_as_memory, slice_registers = map(
        int, (slice_lut_match.group(1), lut_logic_match.group(1),
              lut_memory_match.group(1), slice_ff_match.group(1)))
    dsp_cells = [{"name": name, "ref": ref} for name, ref in re.findall(
        r"NATIVE_OUTPUT_PACKER_V2_DSP_CELL name=(\S+) ref=(\S+)", process.stdout)]
    if len(dsp_cells) != dsp:
        raise ValueError("DSP primitive name census differs from the DSP count")
    bram36_equivalent = ram36 + ram18 / 2
    result["synthesis"] = {
        "status": "PASS_SCREEN" if (
            slice_luts <= 6000 and ff_cells <= 10000 and
            bram36_equivalent <= 2 and dsp == 0 and latch == 0 and blackbox == 0
        ) else "FAIL_SCREEN",
        "slice_luts_including_lutram": slice_luts,
        "lut_as_logic": lut_as_logic, "lut_as_memory": lut_as_memory,
        "primitive_lut_cells": lut_cells,
        "slice_registers": slice_registers, "primitive_ff_cells": ff_cells,
        "ram36": ram36, "ram18": ram18,
        "bram36_equivalent": bram36_equivalent,
        "dsp_count": dsp, "dsp_cells": dsp_cells,
        "latch": latch, "blackbox": blackbox,
        "fixed_limits": {"slice_luts_max_including_lutram": 6000,
                         "ff_max": 10000, "bram36_equivalent_max": 2,
                         "dsp": 0, "latch": 0, "blackbox": 0},
    }
    if result["synthesis"]["status"] != "PASS_SCREEN":
        raise ValueError("OOC synthesis exceeded the fixed resource screen")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--preflight-only", action="store_true",
                       help="Verify the v1 XSim evidence and exact attribute-only diff")
    modes.add_argument("--run-synth", action="store_true",
                       help="Repeat preflight then run exactly one OOC synthesis")
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    evidence = ROOT / "validation/board_z100/native_output_packer_v2" / run_id
    build = ROOT / "deployment/build/z100_native_output_packer_v2" / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    result = {"status": "RUNNING", "run_id": run_id,
              "phase": "HOST_EQUIVALENCE_PREFLIGHT", "commands": [],
              "xsim_rerun": False, "route_attempted": False,
              "board_access": False, "bitstream_created": False}
    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS"):
        env[key] = "1"

    try:
        preflight = check_preflight()
        paths = preflight.pop("source_paths")
        before = source_inventory(paths)
        result["host_preflight"] = preflight
        result["source_sha256_before"] = before
        snapshot(paths, evidence / "source_snapshot")
        (evidence / "launch.json").write_text(json.dumps(result, indent=2) + "\n",
                                               encoding="utf-8")
        if args.run_synth:
            result["phase"] = "OOC_SYNTHESIS_ONLY"
            run_synthesis(build, evidence, env, result)
            result["status"] = "PASS_PRIVATE_NATIVE_OUTPUT_PACKER_V2_OOC_SYNTH_ONLY"
        else:
            result["status"] = "PASS_V1_SIM_BOUND_AND_ATTRIBUTE_EQUIVALENCE_HOST_ONLY"
    except Exception as exc:
        result["status"] = "FAILED_CLOSED"
        result["error"] = f"{type(exc).__name__}: {exc}"
        paths = (V1_RTL, V1_TB, V1_VALIDATOR, V1_REPORT, V1_XSIM_LOG,
                 V2_RTL, Path(__file__))
        paths = tuple(path for path in paths if path.is_file())
        before = source_inventory(paths)

    after = source_inventory(paths)
    result["source_sha256_after"] = after
    if before != after and result["status"].startswith("PASS_"):
        result["status"] = "FAILED_CLOSED"
        result["error"] = "A source dependency changed during validation"
    result["artifact_sha256"] = {
        relative(path): sha_file(path)
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
