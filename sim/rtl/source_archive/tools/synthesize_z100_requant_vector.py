"""Run one isolated Vivado OOC synthesis screen for the frozen 32-lane requantizer.

The result is component-only mapping evidence. It does not place, route, or
qualify clock frequency or the production design.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "deployment/hardware/z100_2026/requant_vector_v1/z100_requant_vector.sv"
TB = ROOT / "deployment/hardware/z100_2026/requant_vector_v1/tb_z100_requant_vector.sv"
VALIDATOR = ROOT / "tools/validate_z100_requant_vector.py"
XSIM_RUN = "20261023T170603.603537Z_1260c0c7"
XSIM_RESULT = ROOT / "validation/board_z100/requant_vector_v1" / XSIM_RUN / "result.json"
BUILD_ROOT = ROOT / "deployment/build/z100_requant_vector_ooc_v1"
EVIDENCE_ROOT = ROOT / "validation/board_z100/requant_vector_ooc_v1"
VIVADO = Path("C:/appload/2026.1/Vivado/bin/vivado.bat")
PART = "xc7z100ffg900-2"
MAX_THREADS = 2

EXPECTED_SOURCE_SHA256 = {
    "deployment\\hardware\\z100_2026\\requant_vector_v1\\z100_requant_vector.sv":
        "9b54f28143369f5ea037253ad181eb69895126bb58bd37776539fd9fd496e1c1",
    "deployment\\hardware\\z100_2026\\requant_vector_v1\\tb_z100_requant_vector.sv":
        "de9ea829c94c4f7b12644ba93183b625f8a0687b636b9e6622a2083f4be1a0c5",
    "tools\\validate_z100_requant_vector.py":
        "bc364342a44c3e1b77e7f92bf00afc733ba13450f94cfcd8ff9a4a347bad6e4f",
    "validation\\board_z100\\requant_vector_v1\\20261023T170603.603537Z_1260c0c7\\result.json":
        "48f8097f7e7c1878e384151560454626dc62f44f42686157284e6a7550e8972e",
}
EXPECTED_XSIM_STATUS = "PASS_XSIM_PRIVATE_32_LANE_CURRENT_MODEL"
EXPECTED_RTL_SHA256 = EXPECTED_SOURCE_SHA256[
    "deployment\\hardware\\z100_2026\\requant_vector_v1\\z100_requant_vector.sv"
]
EXPECTED_XSIM_RESULT_SHA256 = EXPECTED_SOURCE_SHA256[
    "validation\\board_z100\\requant_vector_v1\\20261023T170603.603537Z_1260c0c7\\result.json"
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("/", "\\")


def inventory(paths: list[Path]) -> dict[str, dict[str, Any]]:
    return {
        rel(path): {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in paths
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_paths() -> list[Path]:
    return [RTL, TB, VALIDATOR, XSIM_RESULT, Path(__file__).resolve()]


def validate_frozen_inputs() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    paths = source_paths()
    hashes = inventory(paths)
    for relative, expected in EXPECTED_SOURCE_SHA256.items():
        if hashes.get(relative, {}).get("sha256") != expected:
            raise ValueError(f"frozen source hash mismatch: {relative}")
    xsim = json.loads(XSIM_RESULT.read_text(encoding="utf-8"))
    if xsim.get("status") != EXPECTED_XSIM_STATUS:
        raise ValueError("pinned XSim report does not contain the required pass status")
    if xsim.get("source_sha256_before", {}).get(
        "deployment\\hardware\\z100_2026\\requant_vector_v1\\z100_requant_vector.sv", {}
    ).get("sha256") != EXPECTED_RTL_SHA256:
        raise ValueError("pinned XSim report is not bound to the frozen requantizer RTL")
    if xsim.get("synthesis_or_route") is not False or xsim.get("board_access") is not False:
        raise ValueError("pinned XSim report has unexpected scope flags")
    return xsim, hashes


def tcl_path(path: Path) -> str:
    value = path.resolve().as_posix()
    if "{" in value or "}" in value:
        raise ValueError(f"path cannot be Tcl-brace-quoted safely: {value}")
    # The Tcl template already supplies exactly one enclosing brace pair.
    return value


def make_tcl(evidence: Path, build: Path) -> str:
    template = r'''set_param general.maxThreads 2
if {![string match 2026.1* [version -short]]} {error "Requires Vivado 2026.1"}
puts "REQUANT_VECTOR_OOC_START version=[version -short] part=xc7z100ffg900-2 max_threads=2"
read_verilog -sv {@RTL@}
synth_design -top z100_requant_vector -part xc7z100ffg900-2 -mode out_of_context -flatten_hierarchy rebuilt
create_clock -name requant_internal_clk -period 10.000 [get_ports clk]
report_utilization -file {@UTIL@}
report_utilization -hierarchical -file {@HIER@}
report_timing_summary -delay_type min_max -report_unconstrained -file {@TIMING@}
report_timing -delay_type max -max_paths 50 -file {@PATHS@}
set check_text [check_timing -verbose -return_string]
set check_file [open {@CHECK@} w]
puts $check_file $check_text
close $check_file
write_checkpoint -force {@DCP@}

set census [open {@CENSUS@} w]
puts $census "class\tref_name\tcell_name\tmemory_owner"
set counts [open {@COUNTS@} w]
foreach {kind filter} {
    LUT {REF_NAME =~ LUT*}
    FF {REF_NAME =~ FD*}
    RAMB18 {REF_NAME =~ RAMB18*}
    RAMB36 {REF_NAME =~ RAMB36*}
    DSP {REF_NAME =~ DSP*}
    LATCH {REF_NAME =~ LD*}
    BLACKBOX {IS_BLACKBOX == 1}
} {
    set cells [get_cells -quiet -hier -filter $filter]
    puts $counts "$kind\t[llength $cells]"
    foreach cell $cells {
        set name [get_property NAME $cell]
        set ref [get_property REF_NAME $cell]
        set owner ""
        if {$kind eq "RAMB18" || $kind eq "RAMB36"} {
            if {[regexp {gen_lane\[([0-9]+)\]} $name ignored lane]} {
                set owner [format {lane_%02d} $lane]
            } else {
                set owner "UNMATCHED"
            }
        }
        puts $census "$kind\t$ref\t$name\t$owner"
    }
}
close $counts
close $census

set lut [llength [get_cells -quiet -hier -filter {REF_NAME =~ LUT*}]]
set ff [llength [get_cells -quiet -hier -filter {REF_NAME =~ FD*}]]
set ram36 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB36*}]]
set ram18 [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB18*}]]
set dsp [llength [get_cells -quiet -hier -filter {REF_NAME =~ DSP*}]]
set latch [llength [get_cells -quiet -hier -filter {REF_NAME =~ LD*}]]
set blackbox [llength [get_cells -quiet -hier -filter {IS_BLACKBOX == 1}]]
set bram36eq [expr {$ram36 + $ram18 / 2.0}]
set summary [open {@SUMMARY@} w]
puts $summary "TOOL_VERSION\t[version -short]"
puts $summary "PART\txc7z100ffg900-2"
puts $summary "INTERNAL_CLOCK_PERIOD_NS\t10.000"
puts $summary "LUT_COUNT\t$lut"
puts $summary "FF_COUNT\t$ff"
puts $summary "RAMB18_COUNT\t$ram18"
puts $summary "RAMB36_COUNT\t$ram36"
puts $summary "BRAM36_EQUIVALENT\t$bram36eq"
puts $summary "DSP_COUNT\t$dsp"
puts $summary "LATCH_COUNT\t$latch"
puts $summary "BLACKBOX_COUNT\t$blackbox"
close $summary
puts "REQUANT_VECTOR_OOC_COUNTS lut=$lut ff=$ff ramb18=$ram18 ramb36=$ram36 bram36eq=$bram36eq dsp=$dsp latch=$latch blackbox=$blackbox"
puts "REQUANT_VECTOR_OOC_COMPLETE placement=0 routing=0 external_io_timing_acceptance=0"
exit
'''
    replacements = {
        "@RTL@": tcl_path(RTL),
        "@UTIL@": tcl_path(evidence / "utilization.rpt"),
        "@HIER@": tcl_path(evidence / "hierarchical_utilization.rpt"),
        "@TIMING@": tcl_path(evidence / "timing_unplaced_100mhz_diagnostic.rpt"),
        "@PATHS@": tcl_path(evidence / "timing_paths_unplaced_diagnostic.rpt"),
        "@CHECK@": tcl_path(evidence / "check_timing_unplaced_diagnostic.rpt"),
        "@DCP@": tcl_path(build / "post_synth.dcp"),
        "@CENSUS@": tcl_path(evidence / "primitive_census.tsv"),
        "@COUNTS@": tcl_path(evidence / "primitive_counts.tsv"),
        "@SUMMARY@": tcl_path(evidence / "synthesis_summary.tsv"),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def parse_tsv_counts(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) == 2:
            counts[fields[0]] = int(fields[1])
    return counts


def reconcile_census(evidence: Path, counts: dict[str, int]) -> dict[str, Any]:
    by_lane: dict[str, dict[str, int]] = {}
    unmatched: list[str] = []
    census = evidence / "primitive_census.tsv"
    with census.open("r", encoding="utf-8") as stream:
        header = next(stream).rstrip("\r\n").split("\t")
        expected_header = ["class", "ref_name", "cell_name", "memory_owner"]
        if header != expected_header:
            raise ValueError(f"unexpected primitive census header: {header}")
        row_counts = {kind: 0 for kind in ("LUT", "FF", "RAMB18", "RAMB36", "DSP", "LATCH", "BLACKBOX")}
        for line in stream:
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != 4 or fields[0] not in row_counts:
                raise ValueError(f"malformed primitive census row: {line[:200]!r}")
            kind, _ref, name, owner = fields
            row_counts[kind] += 1
            if kind in ("RAMB18", "RAMB36"):
                if owner == "UNMATCHED" or not re.fullmatch(r"lane_\d{2}", owner):
                    unmatched.append(name)
                    continue
                lane_counts = by_lane.setdefault(owner, {"RAMB18": 0, "RAMB36": 0})
                lane_counts[kind] += 1
        if row_counts != counts:
            raise ValueError(f"primitive census and Vivado count mismatch: {row_counts} != {counts}")

    lane_equivalents = {
        lane: values["RAMB36"] + values["RAMB18"] / 2
        for lane, values in sorted(by_lane.items())
    }
    total_equivalent = counts["RAMB36"] + counts["RAMB18"] / 2
    ownership_reconciled = len(by_lane) == 32 and not unmatched and abs(sum(lane_equivalents.values()) - total_equivalent) < 1e-9
    return {
        "method": "Vivado leaf primitive census grouped by preserved gen_lane hierarchy, cross-checked against direct primitive counts and hierarchical utilization report",
        "expected_generated_lanes": 32,
        "observed_lane_owners": len(by_lane),
        "unmatched_ram_primitive_count": len(unmatched),
        "unmatched_ram_primitive_names": unmatched,
        "ram_primitives_by_lane": by_lane,
        "bram36_equivalent_by_lane": lane_equivalents,
        "aggregate_bram36_equivalent_from_owners": sum(lane_equivalents.values()),
        "aggregate_bram36_equivalent_from_direct_census": total_equivalent,
        "ownership_reconciled": ownership_reconciled,
        "direct_count_crosscheck": True,
    }


def artifact_inventory(build: Path, evidence: Path) -> dict[str, dict[str, Any]]:
    paths = sorted(
        [path for base in (build, evidence) for path in base.rglob("*")
         if path.is_file() and path.name != "result.json"],
        key=lambda path: rel(path),
    )
    return inventory(paths)


def copy_source_snapshot(paths: list[Path], snapshot: Path) -> None:
    for source in paths:
        destination = snapshot / Path(rel(source).replace("\\", "/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def run() -> int:
    xsim, frozen_inventory = validate_frozen_inputs()
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    build = BUILD_ROOT / run_id
    evidence = EVIDENCE_ROOT / run_id
    for directory in (build, evidence):
        if directory.exists():
            raise FileExistsError(f"run directory already exists; refusing to overwrite: {directory}")
        if not directory.resolve().is_relative_to(ROOT):
            raise ValueError(f"output path escapes repository: {directory}")
    build.mkdir(parents=True)
    evidence.mkdir(parents=True)

    sources = source_paths()
    source_before = inventory(sources)
    if source_before != frozen_inventory:
        raise RuntimeError("source inventory changed between preflight and launch")
    copy_source_snapshot(sources, evidence / "source_snapshot")
    write_json(evidence / "source_inventory_before.json", source_before)
    write_json(evidence / "xsim_binding.json", {
        "report_path": rel(XSIM_RESULT),
        "report_status": xsim["status"],
        "report_sha256": source_before[rel(XSIM_RESULT)]["sha256"],
        "frozen_rtl_sha256": EXPECTED_RTL_SHA256,
        "run_id": XSIM_RUN,
        "bound_to_ooc_source_snapshot": True,
    })

    tcl = evidence / "synth.tcl"
    tcl.write_text(make_tcl(evidence, build), encoding="utf-8", newline="\n")
    env = os.environ.copy()
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[name] = "1"
    log = evidence / "vivado.log"
    journal = evidence / "vivado.jou"
    stdout_log = evidence / "vivado_stdout.log"
    command = [str(VIVADO), "-mode", "batch", "-log", str(log), "-journal", str(journal), "-source", str(tcl)]
    result: dict[str, Any] = {
        "run_id": run_id,
        "status": "RUNNING",
        "scope": "one frozen private 32-lane requantizer OOC synthesis; no placement, route, board, or production integration",
        "board_access": False,
        "route_attempted": False,
        "placement_attempted": False,
        "bitstream_created": False,
        "production_integrated": False,
        "device_part": PART,
        "toolchain": {
            "vivado_executable": str(VIVADO),
            "max_threads": MAX_THREADS,
            "numerical_worker_threads": 1,
            "environment_thread_caps": {name: env[name] for name in
                                          ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")},
        },
        "source_sha256_before": source_before,
        "frozen_rtl_sha256": EXPECTED_RTL_SHA256,
        "xsim_report": {
            "run_id": XSIM_RUN,
            "status": xsim["status"],
            "sha256": source_before[rel(XSIM_RESULT)]["sha256"],
        },
        "limits": {
            "dsp": 0,
            "bram36_equivalent_exact": 128,
            "lut_max": 30000,
            "ff_max": 30000,
            "latches": 0,
            "blackboxes": 0,
        },
        "timing_scope": {
            "internal_clock_period_ns": 10.0,
            "purpose": "unplaced diagnostic constraint only",
            "external_io_timing_acceptance": False,
            "frequency_acceptance": False,
            "placement_or_route": False,
        },
        "commands": [{"name": "vivado_ooc_synth", "args": command, "invocation_count": 1}],
        "artifacts": {
            "build_directory": str(build),
            "evidence_directory": str(evidence),
            "checkpoint": str(build / "post_synth.dcp"),
            "tcl": str(tcl),
            "timing_report": str(evidence / "timing_unplaced_100mhz_diagnostic.rpt"),
            "unconstrained_report": str(evidence / "check_timing_unplaced_diagnostic.rpt"),
            "hierarchical_utilization": str(evidence / "hierarchical_utilization.rpt"),
            "primitive_census": str(evidence / "primitive_census.tsv"),
        },
    }
    write_json(evidence / "launch.json", {
        "run_id": run_id,
        "phase": "requant_vector_ooc_synthesis_only",
        "driver_command": [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve())],
        "vivado_command": command,
        "max_threads": MAX_THREADS,
        "numerical_worker_threads": 1,
        "device_part": PART,
        "frozen_rtl_sha256": EXPECTED_RTL_SHA256,
        "bound_xsim_report_sha256": source_before[rel(XSIM_RESULT)]["sha256"],
        "resource_screen": result["limits"],
        "board_access": False,
        "placement": False,
        "routing": False,
    })

    try:
        completed = subprocess.run(
            command,
            cwd=build,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        stdout_log.write_text(completed.stdout, encoding="utf-8")
        result["commands"][0]["return_code"] = completed.returncode
        result["vendor_attempts"] = 1
        warning_lines = [line.strip() for line in completed.stdout.splitlines()
                         if re.search(r"\b(CRITICAL WARNING|WARNING|ERROR):", line, re.IGNORECASE)]
        result["vivado_console_warnings_and_errors"] = warning_lines
        result["vivado_return_code"] = completed.returncode

        metrics_path = evidence / "primitive_counts.tsv"
        if metrics_path.exists():
            counts = parse_tsv_counts(metrics_path)
            result["primitive_counts"] = counts
            required = {"LUT", "FF", "RAMB18", "RAMB36", "DSP", "LATCH", "BLACKBOX"}
            if set(counts) != required:
                raise ValueError(f"missing primitive count categories: {sorted(required - set(counts))}")
            result["bram36_equivalent"] = counts["RAMB36"] + counts["RAMB18"] / 2
            result["memory_ownership"] = reconcile_census(evidence, counts)
            result["resource_gate"] = {
                "dsp_zero": counts["DSP"] == 0,
                "bram36_equivalent_exactly_128": result["bram36_equivalent"] == 128,
                "lut_at_or_below_30000": counts["LUT"] <= 30000,
                "ff_at_or_below_30000": counts["FF"] <= 30000,
                "no_latches": counts["LATCH"] == 0,
                "no_blackboxes": counts["BLACKBOX"] == 0,
                "hierarchical_memory_ownership_reconciled": result["memory_ownership"]["ownership_reconciled"],
            }
        else:
            result["resource_gate"] = {"status": "UNAVAILABLE_COUNTS_NOT_EMITTED"}

        required_artifacts = [
            build / "post_synth.dcp",
            evidence / "utilization.rpt",
            evidence / "hierarchical_utilization.rpt",
            evidence / "timing_unplaced_100mhz_diagnostic.rpt",
            evidence / "check_timing_unplaced_diagnostic.rpt",
            evidence / "primitive_census.tsv",
            evidence / "primitive_counts.tsv",
            evidence / "synthesis_summary.tsv",
        ]
        result["required_artifacts_present"] = {rel(path): path.is_file() for path in required_artifacts}
        all_artifacts_present = all(path.is_file() for path in required_artifacts)
        all_gates_pass = all(result.get("resource_gate", {}).get(key) is True for key in (
            "dsp_zero", "bram36_equivalent_exactly_128", "lut_at_or_below_30000",
            "ff_at_or_below_30000", "no_latches", "no_blackboxes",
            "hierarchical_memory_ownership_reconciled",
        ))
        result["status"] = ("PASS_OOC_RESOURCE_SCREEN" if completed.returncode == 0 and all_artifacts_present and all_gates_pass
                            else "FAILED_CLOSED_OOC_RESOURCE_SCREEN")
        if completed.returncode != 0:
            result["failure"] = f"Vivado OOC returned {completed.returncode}; no retry permitted"
        elif not all_artifacts_present:
            result["failure"] = "one or more required synthesis artifacts were not emitted; no retry permitted"
        elif not all_gates_pass:
            result["failure"] = "fixed resource or memory ownership gate failed; thresholds were not relaxed"
    except Exception as exc:
        result["status"] = "FAILED_CLOSED_OOC_RUN"
        result["failure"] = f"{type(exc).__name__}: {exc}"
        if "vendor_attempts" not in result:
            result["vendor_attempts"] = 0
        raise
    finally:
        source_after = inventory([path for path in sources if path.exists()])
        result["source_sha256_after"] = source_after
        result["source_unchanged"] = source_after == source_before
        if not result["source_unchanged"]:
            result["status"] = "FAILED_SOURCE_INTEGRITY"
            result["failure"] = "frozen input changed during the OOC attempt"
        write_json(evidence / "source_inventory_after.json", source_after)
        result["artifact_sha256"] = artifact_inventory(build, evidence)
        write_json(evidence / "result.json", result)

    print(json.dumps({
        "status": result["status"],
        "run_id": run_id,
        "result": str(evidence / "result.json"),
        "vivado_return_code": result.get("vivado_return_code"),
        "primitive_counts": result.get("primitive_counts"),
        "bram36_equivalent": result.get("bram36_equivalent"),
        "resource_gate": result.get("resource_gate"),
        "source_unchanged": result.get("source_unchanged"),
    }, indent=2))
    return 0 if result["status"] == "PASS_OOC_RESOURCE_SCREEN" and result.get("source_unchanged") else 1


if __name__ == "__main__":
    raise SystemExit(run())
