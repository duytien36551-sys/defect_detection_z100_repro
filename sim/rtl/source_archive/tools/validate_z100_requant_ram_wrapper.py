"""Validate one isolated full-pipeline scalar-RAM packaging experiment."""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import validate_z100_requant_pipeline as baseline  # noqa: E402
from validate_z100_reuse_sync import VIVADO_DEFAULT, run_command, sha256  # noqa: E402

RTL_DIR = ROOT / "deployment/hardware/z100_2026/requant_pipeline_ram_wrapper_v1"
RTL = RTL_DIR / "z100_requant_pipeline_ram_wrapper.sv"
TB = RTL_DIR / "tb_z100_requant_pipeline_ram_wrapper.sv"
BUILD_ROOT = ROOT / "deployment/build/z100_requant_pipeline_ram_wrapper_v1"
EVIDENCE_ROOT = ROOT / "validation/board_z100/requant_pipeline_ram_wrapper_v1"
REFERENCE_C = ROOT / "deployment/hardware/z100_2026/requant_threshold_v0/oracle.c"
REFERENCE_TABLES = ROOT / "deployment/build/z100_requant_threshold_v0/20261021T134827Z_a66a4f65/all_thresholds.bin"
REFERENCE_REPORT = ROOT / "validation/board_z100/requant_threshold_v0/20261021T134827Z_a66a4f65/result.json"
BASELINE_RTL = ROOT / "deployment/hardware/z100_2026/requant_pipeline_v1/z100_requant_pipeline.sv"
BASELINE_TB = ROOT / "deployment/hardware/z100_2026/requant_pipeline_v1/tb_z100_requant_pipeline.sv"
BASELINE_TEST = ROOT / "deployment/tests/test_z100_requant_pipeline.py"
BASELINE_VALIDATOR = ROOT / "tools/validate_z100_requant_pipeline.py"
BASELINE_DOC = ROOT / "docs/z100_requant_pipeline.md"
THRESHOLD_TOOL = ROOT / "tools/z100_requant_thresholds.py"
PACKAGE = ROOT / "deployment/candidates/pin640/validation/20261021_verified/pin/pipeline/package"

# The resource budget is fixed before launching synthesis and is never adapted
# to the observed netlist.
RESOURCE_BUDGET = dict(slice_lut_max=2048, flip_flop_max=2048,
                       ramb18_equivalent_min=1, ramb18_equivalent_max=8, dsp_max=0)
PINNED_BASELINE_SHA256 = {
    "baseline_rtl": "056a4c6135a532a1a0416eb5fe98c984e226761fbae348000cdcb8e5280609d2",
    "baseline_tb": "2919741be32d3abacc4c0a0cf9270df7103af16d60db6b05c25d9ec0b2916402",
    "baseline_validator": "812fe5e5e993dc07720b18f9fcfa779ba75c1d6b19a5150e048cb990ce9233e2",
    "baseline_test": "abea0e2e6a2acdbf464e5ea000b796e3ace4a4832b2c98a331cdfa04b759e507",
    "baseline_doc": "d00696ba527c4e25f308cb8e9f51710dde8b12ee2a69c9257775f9391751a7d1",
    "threshold_tool": "e4b18bffcb23299794b726121ebec174420e3a3232e21ab5562ee27c535693b2",
    "oracle_c": "c3a8b09392b705cfcf83e5fc7e3a5dc18bcccbe644e1d36afc45d4309e542099",
    "threshold_artifact": "f425a5e2311a6739dc5f83daaa75fc6df32d9f9e46a025268d9125964e75c2af",
    "threshold_report": "2af534a2f4b3ba20ce5bbefb190279c8b3b7405f9470ab1e3e84471080d2f189",
    "model_package": "3b3e799d612f29864749e508649765d5cea283a96b3c673a29e0c671319e361e",
    "generated_header": "067ecbcb9f7436f935dbf8f26ee00de3a7440fa1e43bd6646654f15c2dd537ed",
}


def sha(path: Path) -> str:
    return sha256(path)


def _source_files() -> list[Path]:
    return [RTL, TB, Path(__file__).resolve(), ROOT / "deployment/tests/test_z100_requant_ram_wrapper.py",
            ROOT / "docs/z100_requant_ram_wrapper.md", BASELINE_RTL, BASELINE_TB, BASELINE_TEST,
            BASELINE_VALIDATOR, BASELINE_DOC, THRESHOLD_TOOL, REFERENCE_C, REFERENCE_TABLES,
            REFERENCE_REPORT, PACKAGE / "MODEL.V8P", PACKAGE / "v8_generated_model.h"]


def _verify_pins() -> dict[str, str]:
    pins = {
        "baseline_rtl": BASELINE_RTL,
        "baseline_tb": BASELINE_TB,
        "baseline_validator": BASELINE_VALIDATOR,
        "baseline_test": BASELINE_TEST,
        "baseline_doc": BASELINE_DOC,
        "threshold_tool": THRESHOLD_TOOL,
        "oracle_c": REFERENCE_C,
        "threshold_artifact": REFERENCE_TABLES,
        "threshold_report": REFERENCE_REPORT,
        "model_package": PACKAGE / "MODEL.V8P",
        "generated_header": PACKAGE / "v8_generated_model.h",
    }
    actual = {name: sha(path) for name, path in pins.items()}
    # The final two package hashes are pinned by the original validation run.
    expected = {key: value for key, value in PINNED_BASELINE_SHA256.items() if key != "generated_header"}
    if {key: value for key, value in actual.items() if key != "generated_header"} != expected:
        raise ValueError("a frozen baseline/reference hash differs from the reviewed source")
    if actual["generated_header"] != PINNED_BASELINE_SHA256["generated_header"]:
        raise ValueError("packaged generated header hash changed")
    return {str(path.relative_to(ROOT)): sha(path) for path in _source_files()}


def _write_synth_tcl(path: Path, build: Path) -> None:
    def tcl_path(value: Path) -> str:
        return str(value).replace("\\", "/").replace(" ", "\\ ")

    lines = [
        "set_param general.maxThreads 2",
        "create_project -in_memory -part xc7z100ffg900-2",
        f"read_verilog -sv {tcl_path(RTL)}",
        "synth_design -top z100_requant_pipeline_ram_wrapper -part xc7z100ffg900-2 -flatten_hierarchy none",
        "create_clock -name requant_clk -period 5.000 [get_ports clk]",
        f"report_utilization -file {tcl_path(build / 'utilization.rpt')}",
        f"report_timing_summary -delay_type max -max_paths 20 -file {tcl_path(build / 'timing_summary.rpt')}",
        f"write_checkpoint -force {tcl_path(build / 'post_synth.dcp')}",
        "set lut_count [llength [get_cells -hier -filter {REF_NAME =~ LUT*}] ]",
        "set ff_count [llength [get_cells -hier -filter {REF_NAME =~ FD*}] ]",
        "set ramb18_count [llength [get_cells -hier -filter {REF_NAME =~ RAMB18*}] ]",
        "set ramb36_count [llength [get_cells -hier -filter {REF_NAME =~ RAMB36*}] ]",
        "set dsp_count [llength [get_cells -hier -filter {REF_NAME =~ DSP48*}] ]",
        "puts \"RAM_WRAPPER_VIVADO_VERSION [version -short]\"",
        "set ram_cells [get_cells -hier -filter {REF_NAME =~ RAMB18* || REF_NAME =~ RAMB36*}]",
        "foreach c $ram_cells {",
        "  set cname [get_property NAME $c]",
        "  set rname [get_property REF_NAME $c]",
        "  set stage unknown",
        "  if {[regexp {gen_search\\[([0-7])\\]\\.u_table} $cname all idx]} { set stage $idx }",
        "  puts \"RAM_WRAPPER_RAM_INSTANCE stage=$stage cell=$cname ref=$rname\"",
        "  foreach role {ADDRARDADDR ADDRBWRADDR ENARDEN ENBWREN WEA WEB} {",
        "    set pins [get_pins -quiet -of_objects $c -filter \"REF_PIN_NAME =~ $role*\"]",
        "    set nets {}",
        "    foreach p $pins { set nn [get_nets -quiet -of_objects $p]; foreach n $nn { lappend nets [get_property NAME $n] } }",
        "    puts \"RAM_WRAPPER_RAM_PIN stage=$stage cell=$cname role=$role pin_count=[llength $pins] nets=[join [lsort -unique $nets] ,]\"",
        "  }",
        "}",
        "puts \"RAM_WRAPPER_SYNTH_RESULT LUT=$lut_count FF=$ff_count RAMB18=$ramb18_count RAMB36=$ramb36_count DSP=$dsp_count PERIOD_NS=5.000\"",
        "exit",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _run(command: list[str], cwd: Path, log: Path, commands: list[dict[str, Any]]) -> str:
    result = run_command(command, cwd, log)
    commands.append({key: value for key, value in result.items() if key != "output"})
    if result["return_code"] != 0:
        raise RuntimeError(f"command failed ({Path(command[0]).name}): {result['return_code']}")
    return str(result["output"])


def _run_simulation(build: Path, evidence: Path, commands: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    host = baseline._generate_inputs(build)
    if host["actual_c_oracle_vectors"] != 8192 or sum(case["expected_vectors"] for case in host["cases"]) != 11264:
        raise RuntimeError("host-generated exact fixture coverage changed")

    gcc = Path("C:/cbian/mingw64/bin/gcc.exe")
    oracle_exe = build / "upper_bound_oracle.exe"
    gcc_output = _run([str(gcc), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                       "-fno-fast-math", "-ffp-contract=off", str(REFERENCE_C), "-lm", "-o", str(oracle_exe)],
                      build, evidence / "gcc.log", commands)
    if "error:" in gcc_output.lower():
        raise RuntimeError("C oracle compilation emitted an error")
    oracle_output = _run([str(oracle_exe), str(build / "oracle_vectors.bin")], build,
                         evidence / "c_oracle.log", commands)
    if "C_ORACLE_PASS vectors=8192" not in oracle_output:
        raise RuntimeError("pinned C double oracle did not pass all actual-channel vectors")

    bindir = VIVADO_DEFAULT.parent
    sim_commands = [
        ("xvlog", [str(bindir / "xvlog.bat"), "-sv", str(RTL), str(TB)]),
        ("xelab", [str(bindir / "xelab.bat"), "-mt", "2", "tb_z100_requant_pipeline_ram_wrapper",
                    "-s", "requant_pipeline_ram_wrapper_sim"]),
        ("xsim", [str(bindir / "xsim.bat"), "requant_pipeline_ram_wrapper_sim", "-runall"]),
    ]
    sim_output = ""
    for name, command in sim_commands:
        sim_output = _run(command, build, evidence / f"{name}.log", commands)
    if "Fatal:" in sim_output or "FAIL" in sim_output:
        raise RuntimeError("XSim reported a fatal/error result")
    summary = re.search(
        r"REQUANT_PIPELINE_RAM_WRAPPER_PASS cases=(\d+) actual_tables=(\d+) synthetic_tables=(\d+) "
        r"config_errors=(\d+) premature_commit=(\d+) cancel=(\d+) reset=(\d+) "
        r"stage_cancel=(\d+) stage_reset=(\d+) idle_abort=(\d+) config_abort=(\d+) context_swap=(\d+) "
        r"latency_no_stall=(\d+) steady_accept_ii=(\d+) steady_result_ii=(\d+)", sim_output)
    expected = (11264, 8, 3, 2, 1, 1, 1, 8, 8, 2, 2, 1, 8, 1, 1)
    if not summary or tuple(map(int, summary.groups())) != expected:
        raise RuntimeError("XSim summary did not prove the complete numeric and abort coverage")
    metrics = [
        dict(case_id=int(case), vectors=int(vectors), no_stall_latency_cycles=int(latency),
             observed_latency_min=int(min_latency), observed_latency_max=int(max_latency),
             accepted_interval_cycles=int(accept_ii), result_interval_cycles=int(result_ii),
             blocked_output_cycles=int(blocked))
        for case, vectors, latency, min_latency, max_latency, accept_ii, result_ii, blocked
        in re.findall(r"PIPE_CASE id=(\d+) vectors=(\d+) no_stall_latency=(\d+) observed_latency_min=(\d+) "
                      r"observed_latency_max=(\d+) accept_ii=(\d+) result_ii=(\d+) blocked_cycles=(\d+)", sim_output)
    ]
    if len(metrics) != 11 or any(
        m["vectors"] != 1024 or m["no_stall_latency_cycles"] != 8 or
        m["accepted_interval_cycles"] != 1 or m["result_interval_cycles"] != 1 or
        m["blocked_output_cycles"] <= 0 for m in metrics
    ):
        raise RuntimeError("XSim did not demonstrate eight-cycle latency, 11,264 outputs and steady II=1")
    result = dict(status="PASS", host=host, total_checked_results=11264, actual_channel_c_oracle_vectors=8192,
                  actual_tables=8, synthetic_tables=3, baseline_cases=metrics,
                  config_rejections=2, premature_commit_rejections=1,
                  baseline_cancel_tests=1, baseline_reset_tests=1,
                  stage_cancel_tests=8, stage_reset_tests=8, idle_abort_tests=2,
                  configuration_abort_tests=2, distinct_table_context_swaps=1,
                  no_stall_latency_cycles=8, steady_accept_interval_cycles=1,
                  steady_result_interval_cycles=1,
                  handshake_latency_definition="accepting in_valid&&in_ready rising edge to corresponding out_valid&&out_ready rising edge")
    return result, oracle_exe.name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-synth", action="store_true", help="run host/oracle/XSim only")
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    evidence = EVIDENCE_ROOT / run_id
    build = BUILD_ROOT / run_id
    evidence.mkdir(parents=True)
    build.mkdir(parents=True)
    source_files = _source_files()
    source_hashes = _verify_pins()
    launch = dict(run_id=run_id, source_sha256=source_hashes, resource_budget=RESOURCE_BUDGET,
                  synthesis_scope="one OOC synthesis only after host/oracle/XSim pass; no route or bitstream")
    (evidence / "launch.json").write_text(json.dumps(launch, indent=2) + "\n", encoding="utf-8")
    result: dict[str, Any] = dict(run_id=run_id, status="RUNNING", source_sha256=source_hashes,
                                  resource_budget=RESOURCE_BUDGET, physical_board_tested=False,
                                  production_integrated=False, final_model_accepted=False,
                                  release_eligible=False)
    commands: list[dict[str, Any]] = []
    try:
        simulation, oracle_exe_name = _run_simulation(build, evidence, commands)
        result["simulation"] = simulation
        synthesis = None
        if not args.no_synth:
            tcl = build / "synth.tcl"
            _write_synth_tcl(tcl, build)
            synth_output = _run([str(VIVADO_DEFAULT), "-mode", "batch", "-nojournal", "-nolog", "-source", str(tcl)],
                                build, evidence / "vivado_synth.log", commands)
            match = re.findall(r"RAM_WRAPPER_SYNTH_RESULT LUT=(\d+) FF=(\d+) RAMB18=(\d+) RAMB36=(\d+) DSP=(\d+) PERIOD_NS=([0-9.]+)", synth_output)
            if len(match) != 1:
                raise RuntimeError("Vivado synthesis summary was missing or duplicated")
            lut, ff, ramb18, ramb36, dsp, period_ns = match[0]
            lut, ff, ramb18, ramb36, dsp = map(int, (lut, ff, ramb18, ramb36, dsp))
            ram_equiv = ramb18 + 2 * ramb36
            ram_rows = [dict(stage=int(stage), cell=cell, primitive=primitive)
                        for stage, cell, primitive in re.findall(
                            r"RAM_WRAPPER_RAM_INSTANCE stage=([0-7]) cell=(\S+) ref=(RAMB18\S*|RAMB36\S*)", synth_output)]
            pin_rows = [dict(stage=int(stage) if stage.isdigit() else None, cell=cell, role=role,
                             pin_count=int(count), nets=nets)
                        for stage, cell, role, count, nets in re.findall(
                            r"RAM_WRAPPER_RAM_PIN stage=(\S+) cell=(\S+) role=(\S+) pin_count=(\d+) nets=(.*)", synth_output)]
            if not (lut <= RESOURCE_BUDGET["slice_lut_max"] and
                    ff <= RESOURCE_BUDGET["flip_flop_max"] and
                    RESOURCE_BUDGET["ramb18_equivalent_min"] <= ram_equiv <= RESOURCE_BUDGET["ramb18_equivalent_max"] and
                    dsp <= RESOURCE_BUDGET["dsp_max"]):
                raise RuntimeError("observed synthesis resources exceed the predeclared fixed budget")
            if len(ram_rows) != ramb18 + ramb36:
                raise RuntimeError("Vivado RAM instance ownership report count does not match mapped cells")
            synthesis = dict(status="PASS_FIXED_BUDGET_OOC_SYNTH_ONLY", slice_lut=lut, flip_flops=ff,
                             ramb18=ramb18, ramb36=ramb36, ramb18_equivalent=ram_equiv, dsp=dsp,
                             requested_period_ns=float(period_ns), timing_scope="unplaced post-synthesis estimate; no route; no 200 MHz acceptance",
                             mapped_ram_instances=ram_rows, ram_pin_connections=pin_rows,
                             table_instances=8, logical_table_depth=255, logical_table_width_bits=33,
                             memory_ownership_interpretation="one RAM wrapper is instantiated per search stage; only mapped primitives listed above count as physical RAM evidence")
        result["synthesis"] = synthesis
        result["commands"] = commands
        after = {str(path.relative_to(ROOT)): sha(path) for path in source_files}
        if after != source_hashes:
            raise RuntimeError("a bound source or immutable input changed during the run")
        result["source_sha256_after"] = after
        artifacts = [*build.glob("*.hex"), build / "oracle_vectors.bin", build / oracle_exe_name,
                     *evidence.glob("*.log"), build / "synth.tcl"]
        artifacts.extend(path for path in (build / "utilization.rpt", build / "timing_summary.rpt", build / "post_synth.dcp") if path.exists())
        result["artifact_sha256"] = {str(path.relative_to(ROOT)): sha(path) for path in artifacts if path.exists()}
        result["scope"] = dict(lane_count=1, elastic_search_stages=8, steady_state_ii_cycles=1,
                               no_stall_latency_cycles=8, production_interface_or_dma_integrated=False,
                               timing_closed=False, route_performed=False, bitstream_created=False,
                               root_cause_claimed=False)
        result["status"] = "PASS_PRIVATE_RAM_WRAPPER_EXPERIMENT"
    except Exception as exc:
        result["status"] = "FAILED"
        result["failure"] = f"{type(exc).__name__}: {exc}"
        result["commands"] = commands
        result["source_sha256_after"] = {str(path.relative_to(ROOT)): sha(path) for path in source_files if path.exists()}
        (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        raise

    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(status=result["status"], run_id=run_id, report=str(evidence / "result.json"),
                          simulation=result["simulation"], synthesis=result["synthesis"]), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
