"""Prove addressed scatter-store -> next-layer window reuse without DDR copies."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'deployment/hardware/z100_2026/feature_window_v2/z100_feature_window.sv'
BANK = ROOT / 'deployment/hardware/z100_2026/feature_banks_addressed_v1/z100_feature_banks_addressed.sv'
OWNED = ROOT / 'deployment/hardware/z100_2026/feature_window_addressed_v3'
RTL = OWNED / 'z100_feature_window_addressed.sv'
TB = OWNED / 'tb_z100_feature_window_addressed.sv'
BASE = ROOT / 'tools/validate_z100_feature_window_v2.py'
VENDOR = Path('C:/appload/2026.1/Vivado/bin')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(paths):
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--execute', action='store_true')
    ap.add_argument('--bank-report', type=Path)
    args = ap.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    evidence = ROOT / 'validation/board_z100/feature_window_addressed_v3' / stamp
    build = ROOT / 'deployment/build/z100_feature_window_addressed_v3' / stamp
    evidence.mkdir(parents=True, exist_ok=False); build.mkdir(parents=True, exist_ok=False)
    paths = [OLD, BANK, RTL, TB, BASE, Path(__file__).resolve(),
             ROOT / 'tools/z100_feature_window_layout.py',
             ROOT / 'deployment/hardware/z100_2026/feature_window_v2/tb_z100_feature_window.sv']
    if args.bank_report:
        paths.append(args.bank_report.resolve())
    before = inventory(paths)
    result = dict(status='RUNNING', source_sha256_before=before, commands=[],
                  board_access=False, production_integrated=False,
                  full_pipeline_30fps_accepted=False)
    report = evidence / 'result.json'
    try:
        require(sha(OLD) == 'd6208a8b0f40f36c407c6ccc883f34fa70fc026025181015d7dc16bca92a9857',
                'Frozen window v2 identity changed')
        require(sha(BANK) == '62c30b0487a54edd6125affa492b3d79c2987203f8cba992fae6560051df656a',
                'Addressed bank identity changed; review before rebinding')
        # All address generation, validation, mapping, elastic stages and gather
        # logic below the bank instance must be byte-identical to proven v2.
        anchor = '    wire signed [12:0] input_width_extended'
        require(OLD.read_text().split(anchor, 1)[1] == RTL.read_text().split(anchor, 1)[1],
                'Window algorithm differs from frozen v2')
        spec = importlib.util.spec_from_file_location('frozen_window_fixture', BASE)
        v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)
        reference = v.generate_vectors(build)
        require(reference['vectors'] == 784 and reference['shape'] == [7, 8, 40], 'Fixture identity')
        # Regenerate only loader ordering. Every expected window is still the
        # original independent CHW oracle, not the bank mapping under test.
        canonical = (build / 'load_words.hex').read_text().splitlines()
        channels, height, width = reference['shape']; xwords = (width+15)//16
        addresses = []
        for channel_base in range(0, channels, 32):
            for row in range(height):
                for xword in range(xwords):
                    for subgroup in range((min(32, channels-channel_base)+3)//4):
                        addresses.append(((channel_base//4+subgroup)*height+row)*xwords+xword)
        require(sorted(addresses) == list(range(reference['load_words'])), 'Scatter holes or duplicates')
        require(addresses != sorted(addresses), 'Fixture must exercise nonlinear scatter')
        (build / 'load_words.hex').write_text(''.join(canonical[a]+'\n' for a in addresses))
        (build / 'load_addresses.hex').write_text(''.join(f'{a:04x}\n' for a in addresses))
        reference.update(addressed_load_words=len(addresses), nonlinear_address_order=True,
                         address_generation_and_gather_byte_identical_to_v2=True,
                         feature_copy_or_ddr_roundtrip=False)
        result['reference'] = reference
        for p in paths:
            destination = evidence / 'source_snapshot' / p.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(p, destination)
        result['status'] = 'PASS_HOST_ADDRESSED_WINDOW_FIXTURE_VENDOR_PENDING'
        if args.execute:
            require(args.bank_report is not None, 'Passing addressed-bank report required')
            dependency = json.loads(args.bank_report.read_text())
            require(dependency['status'].startswith('PASS_') and
                    dependency.get('simulation', {}).get('status') == 'PASS' and
                    dependency.get('synthesis', {}).get('status', '').startswith('PASS'),
                    'Addressed bank prerequisite not accepted')
            require(dependency['source_sha256_before'] == dependency['source_sha256_after'],
                    'Bank prerequisite input mutation')
            normalized = {name.replace('\\', '/'): value for name, value in
                          dependency['source_sha256_before'].items()}
            require(normalized.get(BANK.relative_to(ROOT).as_posix()) == sha(BANK),
                    'Bank source identity missing in prerequisite')
            for name, value in normalized.items():
                require(sha(ROOT/name) == value, f'Bank dependency input drift: {name}')
            result['bank_prerequisite_report'] = str(args.bank_report.resolve().relative_to(ROOT))
            result['bank_prerequisite_sha256'] = sha(args.bank_report)
            env = dict(os.environ)
            for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
                env[key] = '1'

            def run(name, argv):
                proc = subprocess.run(list(map(str, argv)), cwd=build, env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, encoding='utf-8', errors='replace')
                (evidence / f'{name}.log').write_text(proc.stdout)
                result['commands'].append(dict(name=name, argv=list(map(str, argv)),
                                               return_code=proc.returncode))
                require(proc.returncode == 0, f'{name} process failed')
                require(not re.search(r'^\s*(?:Fatal:|ERROR:)', proc.stdout, re.M), f'{name} fatal')
                return proc.stdout

            run('xvlog', [VENDOR/'xvlog.bat', '-sv', BANK, RTL, TB])
            run('xelab', [VENDOR/'xelab.bat', '-mt', '2', 'tb_z100_feature_window_addressed',
                          '-s', 'feature_window_addressed_sim'])
            sim = run('xsim', [VENDOR/'xsim.bat', 'feature_window_addressed_sim', '-runall'])
            matches = re.findall(r'^FEATURE_WINDOW_ADDRESSED_V3_PASS vectors=(\d+) results=(\d+) stalls=(\d+) '
                                 r'max_consecutive=(\d+) geometry_errors=1 row_overflow_errors=1 '
                                 r'inactive_row_control=1 cancel_full=1\s*$', sim, re.M)
            require(len(matches) == 1, 'Missing unique anchored simulation marker')
            sent, received, stalls, streak = map(int, matches[0])
            require(sent == received == 784 and stalls > 0 and streak >= 8, 'Window coverage')
            result['simulation'] = dict(status='PASS', windows=784, stalls=stalls,
                                        max_consecutive_results=streak, scatter_to_next_window=True)
            tcl = build / 'synth.tcl'
            tcl.write_text('''set_param general.maxThreads 2
if {![string match 2026.1* [version -short]]} {error "Requires Vivado2026.1"}
read_verilog -sv {%s}
read_verilog -sv {%s}
synth_design -top z100_feature_window_addressed -part xc7z100ffg900-2 -mode out_of_context
create_clock -period 10 [get_ports clk]
report_utilization -file {%s}
set leaf [get_cells -hier -filter {IS_PRIMITIVE == 1}]
foreach {kind pattern} {LUT LUT* FF FD* RAM36 RAMB36* RAM18 RAMB18* DSP DSP* LATCH LD*} {
    puts "ADDRESSED_WINDOW_CENSUS $kind [llength [filter $leaf REF_NAME=~$pattern]]"
}
puts "ADDRESSED_WINDOW_CENSUS BLACKBOX [llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]"
write_checkpoint -force {%s}
''' % (BANK.as_posix(), RTL.as_posix(), (evidence/'utilization.rpt').as_posix(),
       (build/'post_synth.dcp').as_posix()))
            synth = run('vivado_ooc', [VENDOR/'vivado.bat', '-mode', 'batch', '-source', tcl,
                                       '-log', evidence/'vivado.log', '-journal', evidence/'vivado.jou'])
            counts = {k: int(x) for k, x in re.findall(r'^ADDRESSED_WINDOW_CENSUS (\w+) (\d+)\s*$', synth, re.M)}
            require(set(counts) == {'LUT', 'FF', 'RAM36', 'RAM18', 'DSP', 'LATCH', 'BLACKBOX'},
                    'Incomplete primitive census')
            require(counts['RAM36']+counts['RAM18']/2 == 128 and counts['DSP'] ==
                    counts['LATCH'] == counts['BLACKBOX'] == 0 and counts['LUT'] <= 24000 and
                    counts['FF'] <= 6000, 'Addressed window fixed OOC resource gate')
            result['synthesis'] = dict(status='PASS_OOC_RESOURCE_SCREEN_ONLY', primitive_counts=counts,
                                        bram36eq=128, route_or_clock_accepted=False)
            result['status'] = 'PASS_PRIVATE_ADDRESSED_STORE_TO_WINDOW_XSIM_OOC_ONLY'
    except Exception as exc:
        result.update(status='FAILED_CLOSED', error=f'{type(exc).__name__}: {exc}')
    finally:
        result['source_sha256_after'] = inventory(paths)
        if result['source_sha256_after'] != before:
            result.update(status='FAILED_SOURCE_INTEGRITY', error='Source changed during validation')
        result['artifact_sha256'] = {str(p.relative_to(ROOT)): sha(p) for base in (build, evidence)
                                    for p in base.rglob('*') if p.is_file() and p != report}
        report.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(status=result['status'], report=str(report), error=result.get('error')), indent=2))
    return 0 if result['status'].startswith('PASS_') else 1


if __name__ == '__main__':
    raise SystemExit(main())
