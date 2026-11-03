"""Serialize staged-packer parity, actual Pool regression and matched OOC builds."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "build/v12p_d46da432/rtl"
OWN = ROOT / "deployment/hardware/z100_2026/native_output_packer_staged_v3"
VENDOR = Path("C:/appload/2026.1/Vivado/bin")
BASE_SHA = "f13d0686e94480e78f967ebb5242ef5686728440bd527b640c26541d54c25c31"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def vendor_idle() -> None:
    cmd = "$p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('vivado.exe','xsim.exe','xsimk.exe','xelab.exe','xvlog.exe') }); $p | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
    check(proc.returncode == 0 and not proc.stdout.strip(), "Vendor slot occupied or process inventory failed: " + proc.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-vendor", action="store_true")
    parser.add_argument("--implement-components", action="store_true")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = ROOT / "validation/board_z100/packer_staged_v3" / stamp
    build = ROOT / "build" / ("pkstage_" + stamp[-14:])
    out.mkdir(parents=True, exist_ok=False)
    build.mkdir(parents=True, exist_ok=False)
    report = out / "result.json"
    result = dict(status="RUNNING", commands=[], board_access=False,
                  full_platform_accepted=False, full_pipeline_30fps_accepted=False,
                  implementation_scope="Standalone packer only; no full2016DSP core or platform build")
    inputs: dict[str, str] = {}
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = None
    owns = False
    def save() -> None:
        report.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    def bind(path: Path) -> Path:
        inputs[path.relative_to(ROOT).as_posix()] = sha(path)
        return path
    def run(label: str, argv: list, work: Path = build) -> str:
        vendor_idle()
        result["phase"] = label
        entry = dict(label=label, argv=list(map(str, argv)), started_utc=datetime.now(timezone.utc).isoformat())
        result["commands"].append(entry)
        save()
        log = out / (label+".log")
        start = time.monotonic()
        with log.open("w", encoding="utf-8") as stream:
            proc = subprocess.Popen(entry["argv"], cwd=work, stdout=stream, stderr=subprocess.STDOUT,
                                    env=dict(os.environ, XILINX_LOCAL_USER_DATA="no", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1"))
            entry["pid"] = proc.pid
            save()
            code = proc.wait()
        entry.update(return_code=code, wall_seconds=time.monotonic()-start)
        save()
        text = log.read_text(encoding="utf-8", errors="replace")
        check(code == 0 and not re.search(r"^\s*(ERROR:|Fatal:|FATAL:)", text, re.M), "Vendor failure " + label)
        return text
    try:
        baseline = bind(FROZEN / "z100_native_output_packer.sv")
        check(sha(baseline) == BASE_SHA, "Frozen20site baseline changed")
        candidate = bind(OWN / "z100_native_output_packer.sv")
        tb = bind(OWN / "tb_z100_native_output_packer_staged.sv")
        bind(Path(__file__))
        ref = build / "z100_native_output_packer_reference.sv"
        text = baseline.read_text()
        check(text.count("module z100_native_output_packer #(") == 1, "Unique module rename seam")
        candidate_text = candidate.read_text()
        signature = r"module z100_native_output_packer.*?\);"
        check(re.search(signature, text, re.S).group() == re.search(signature, candidate_text, re.S).group(),
              "Public interface changed")
        runtime_start = "    wire [10:0] channels_left"
        runtime_end = "    integer reset_index;"
        check(text[text.index(runtime_start):text.index(runtime_end)] ==
              candidate_text[candidate_text.index(runtime_start):candidate_text.index(runtime_end)],
              "Runtime combinational datapath changed")
        sequential_start = "            if (in_valid && in_ready)"
        check(text[text.index(sequential_start):] == candidate_text[candidate_text.index(sequential_start):],
              "Runtime input/output sequence changed")
        result["mechanical_contract"] = dict(public_interface_identical=True,
                                               runtime_combinational_identical=True,
                                               runtime_input_output_sequence_identical=True)
        ref.write_text(text.replace("module z100_native_output_packer #(", "module z100_native_output_packer_reference #("), encoding="utf-8")
        staged = build / candidate.name
        shutil.copy2(candidate, staged)
        shutil.copy2(tb, build / tb.name)
        result["source_sha256_before"] = inputs
        result["baseline_sha256"] = BASE_SHA
        save()
        if not args.run_vendor:
            result["status"] = "PASS_SOURCE_PREFLIGHT_ONLY"
            return 0
        mutex = kernel.CreateMutexW(None, False, "Local\\Z100_Vivado_Implementation")
        check(bool(mutex), "Cannot create shared implementation mutex")
        owns = kernel.WaitForSingleObject(mutex, 0) in (0, 0x80)
        check(owns, "Another controlled implementation owns vendor slot")
        vendor_idle()
        run("xvlog_unit", [VENDOR/"xvlog.bat", "-sv", ref, staged, build/tb.name])
        run("xelab_unit", [VENDOR/"xelab.bat", "-mt", "2", "tb_z100_native_output_packer_staged", "-s", "pkstage_unit"])
        sim = run("xsim_unit", [VENDOR/"xsim.bat", "pkstage_unit", "-runall"])
        check(re.search(r"^PACKER_STAGED_PASS\b", sim, re.M) is not None, "Missing completed staged packer marker")
        result["simulation_markers"] = re.findall(r"^PACKER_STAGED[^\n]*", sim, re.M)
        save()

        # Actual frozen Pool consumer plus independent signed5x5 output oracle.
        # The old cycle-miter is intentionally excluded because cfg latency is
        # explicitly changed; all numeric, cancel, fault and stall checks remain.
        pool_tb_source = bind(ROOT / "deployment/hardware/z100_2026/pool_tapxy_v9/tb_z100_pool_tapxy.sv")
        pool_text = pool_tb_source.read_text()
        pool_text = pool_text.replace("module tb_z100_pool_tapxy;", "module tb_z100_pool_staged;")
        pool_text = pool_text.replace("||dut.tapxy_monitor.window_checks<16000||dut.tapxy_monitor.output_checks<1304", "")
        old_display = next(line for line in pool_text.splitlines() if '$display("POOL_TAPXY_PASS' in line)
        pool_text = pool_text.replace(old_display, '  $display("POOL_STAGED_PASS complete_jobs=3 signed_packed_words=1304 independent_bytes=83456 cancel_cases=3 fault_recovery=1 bad_epoch=1 window_holds=%0d output_holds=%0d",window_holds,output_holds);')
        check("tapxy_monitor" not in pool_text, "Unremoved old exact-cycle observer")
        pool_tb = build / "tb_z100_pool_staged.sv"
        pool_tb.write_text(pool_text, encoding="utf-8")
        pool_rtl = [bind(FROZEN/name) for name in ("z100_maxpool_vector.sv", "z100_maxpool_collect32.sv", "z100_maxpool_window20_tapxy_v3.sv")]
        run("xvlog_pool", [VENDOR/"xvlog.bat", "-sv", *pool_rtl, pool_tb])
        run("xelab_pool", [VENDOR/"xelab.bat", "-mt", "2", "tb_z100_pool_staged", "-s", "pkstage_pool"])
        pool_sim = run("xsim_pool", [VENDOR/"xsim.bat", "pkstage_pool", "-runall"])
        check(re.search(r"^POOL_STAGED_PASS complete_jobs=3 signed_packed_words=1304 independent_bytes=83456", pool_sim, re.M) is not None, "Actual Pool numeric/recovery regression failed")
        result["pool_simulation_marker"] = re.findall(r"^POOL_STAGED_PASS[^\n]*", pool_sim, re.M)
        result["component_results"] = {}
        for arm, source in (("baseline", baseline), ("candidate", staged)):
            folder = out / arm
            folder.mkdir()
            tcl = build / (arm+"_synth.tcl")
            lines = ["set_param general.maxThreads 8", 'if {![string match 2026.1* [version -short]]} {error "Wrong Vivado version"}',
                     "read_verilog -sv {"+source.as_posix()+"}",
                     "synth_design -top z100_native_output_packer -part xc7z100ffg900-2 -mode out_of_context",
                     "create_clock -period 10 -name row_clk [get_ports clk]",
                     "set_input_delay 0 -clock row_clk [get_ports -filter {DIRECTION == IN && NAME != clk}]",
                     "set_output_delay 0 -clock row_clk [get_ports -filter {DIRECTION == OUT}]",
                     "report_utilization -file {"+(folder/"utilization_synth.rpt").as_posix()+"}",
                     "report_timing_summary -report_unconstrained -file {"+(folder/"timing_synth.rpt").as_posix()+"}",
                     "write_checkpoint -force {"+(folder/"post_synth.dcp").as_posix()+"}",
                     "set leaf [get_cells -hier -filter {IS_PRIMITIVE == 1}]",
                     'foreach {kind pattern} {LUT LUT* FF FD* DSP DSP* RAM36 RAMB36* RAM18 RAMB18* LATCH LD* CARRY CARRY*} {puts "PACKER_CENSUS $kind [llength [filter $leaf REF_NAME=~$pattern]]"}',
                     'puts "PACKER_CENSUS BLACKBOX [llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]"']
            if args.implement_components:
                lines += ["opt_design", "place_design", "phys_opt_design -hold_fix", "route_design -directive Default",
                          "write_checkpoint -force {"+(folder/"post_route.dcp").as_posix()+"}",
                          "report_timing_summary -delay_type min_max -report_unconstrained -file {"+(folder/"timing_routed.rpt").as_posix()+"}",
                          "report_timing -max_paths 20 -input_pins -file {"+(folder/"critical_paths_routed.rpt").as_posix()+"}",
                          "report_route_status -file {"+(folder/"route_status.rpt").as_posix()+"}",
                          "report_utilization -file {"+(folder/"utilization_routed.rpt").as_posix()+"}",
                          "report_drc -file {"+(folder/"drc_routed.rpt").as_posix()+"}",
                          "set checks [check_timing -verbose -return_string]",
                          "set checkfile [open {"+(folder/"check_timing.rpt").as_posix()+"} w]",
                          "puts $checkfile $checks", "close $checkfile"]
            lines += ['puts "PACKER_COMPONENT_COMPLETE '+arm+'"', "exit 0"]
            tcl.write_text("\n".join(lines)+"\n", encoding="utf-8")
            synthesis = run("vivado_"+arm, [VENDOR/"vivado.bat", "-mode", "batch", "-source", tcl,
                                           "-log", folder/"vivado.log", "-journal", folder/"vivado.jou"])
            counts = {k:int(v) for k,v in re.findall(r"^PACKER_CENSUS (\w+) (\d+)\s*$", synthesis, re.M)}
            check(set(counts) == {"LUT","FF","DSP","RAM36","RAM18","LATCH","CARRY","BLACKBOX"}, "Incomplete census")
            check(counts["DSP"] == counts["LATCH"] == counts["BLACKBOX"] == 0, "Unexpected primitive mapping")
            check("PACKER_COMPONENT_COMPLETE "+arm in synthesis, "Incomplete component run")
            result["component_results"][arm] = dict(primitive_counts=counts, routed=args.implement_components)
            save()
        result["status"] = "PASS_PACKER_PARITY_ACTUAL_POOL_AND_MATCHED_COMPONENT_BUILDS_ONLY"
        result["phase"] = "COMPLETE_PRIMARY_REVIEW_REQUIRED"
    except Exception as exc:
        result.update(status="FAILED_CLOSED", error=f"{type(exc).__name__}: {exc}")
    finally:
        result["source_sha256_after"] = {name:sha(ROOT/name) for name in inputs}
        result["source_sha256_before"] = inputs
        if result["source_sha256_after"] != inputs:
            result.update(status="FAILED_SOURCE_INTEGRITY", error="Inputs changed during validation")
        result["artifact_sha256"] = {p.relative_to(ROOT).as_posix():sha(p) for base in (out,build) for p in base.rglob("*") if p.is_file() and p != report}
        save()
        if owns:
            kernel.ReleaseMutex(mutex)
        if mutex:
            kernel.CloseHandle(mutex)
        print(json.dumps(dict(status=result["status"], report=str(report), error=result.get("error"))))
    return int(result["status"].startswith("FAILED"))


if __name__ == "__main__":
    sys.exit(main())
