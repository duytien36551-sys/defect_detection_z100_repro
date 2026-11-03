"""Run real first-event numeric after a reviewed legal-route disposition.

Physical timing failure remains unaccepted. This independent simulation cannot
promote timing; at most one other small Xsim unit flow may be live.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess

from validate_z100_rom_prefetch_first_conv_v2 import repo_path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prepared', type=Path, required=True)
    ap.add_argument('--completed-route-review', type=Path, required=True)
    a = ap.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out = ROOT / 'validation/board_z100/native_conv_numeric_v3' / stamp
    out.mkdir(parents=True)
    execution_build = ROOT / 'build' / ('ncn3_' + stamp[9:])
    execution_build.mkdir(parents=True)
    report = out / 'result.json'
    result = dict(status='PREFLIGHT', board_access=False, fullgraph_execution_accepted=False,
        full_pipeline_30fps_accepted=False, scope='Actual whole first Conv event numerical simulation only; no graph-ledger tensor publication or hardware inference.')
    pins = {}

    def save():
        report.write_text(json.dumps(result, indent=2) + '\n')

    try:
        prepared = a.prepared.resolve()
        route_review = a.completed_route_review.resolve()
        require(prepared.is_relative_to(ROOT) and route_review.is_relative_to(ROOT), 'Project-bound prerequisites')
        route = json.loads(route_review.read_text())
        require(route['status'] in ['REVIEWED_PRIVATE_V10_LEGAL_ROUTE_INTERNAL_TIMING_PASS', 'REVIEWED_PRIVATE_V10_LEGAL_ROUTE_TIMING_NOT_MET'], 'Actual completed legal-route review')
        require(route['routable_nets'] == route['fully_routed_nets'] == 347377 and route['routing_error_nets'] == 0, 'Complete actual legal routing')
        # This reviewer records the exact producer-report digest rather than
        # copying its complete source map. Follow and verify that closed map.
        producer_path = ROOT / route['route_report']
        require(sha(producer_path) == route['route_report_sha256'], 'Exact reviewed route producer')
        producer = json.loads(producer_path.read_text())
        require(producer['command']['return_code'] == 0 and producer['source_sha256_before'] == producer['source_sha256_after'], 'Completed stable route producer')
        for name, digest in {**producer['source_sha256_after'], **producer['artifact_sha256']}.items():
            require(sha(repo_path(name)) == digest, 'Closed route evidence drift: ' + name)
            pins[name] = digest
        pins[str(route_review.relative_to(ROOT))] = sha(route_review)
        pins[str(producer_path.relative_to(ROOT))] = sha(producer_path)
        reviewer_path = ROOT / 'tools/review_z100_v10_route_recovery_v1.py'
        require(sha(reviewer_path) == route['reviewer_sha256'], 'Bound independent route reviewer')
        pins[str(reviewer_path.relative_to(ROOT))] = sha(reviewer_path)
        result.update(priority_route_disposition=route['status'], physical_timing_accepted=False,
            route_review=str(route_review.relative_to(ROOT)), route_setup_worst_slack_ns=route['setup_worst_slack_ns'])
        p = json.loads(prepared.read_text())
        require(p['status'] == 'PREPARED_LOCAL_ELABORATION_PASS_NUMERICAL_UNEXECUTED' and p['local_elaboration']['return_code'] == 0, 'Actual real-arithmetic numerical harness source closure')
        require(p['source_sha256_before'] and p['source_sha256_before'] == p['source_sha256_after'], 'Stable prepared inputs')
        for name, digest in {**p['source_sha256_after'], **p['artifact_sha256']}.items():
            require(sha(repo_path(name)) == digest, 'Prepared input/output drift: ' + name)
            pins[name] = digest
        cmd = json.loads(json.dumps(p['commands']['vendor_numerical']))
        build = Path(cmd['cwd']).resolve()
        require(build.is_relative_to(ROOT) and len(cmd['steps']) == 3, 'Bounded actual vendor command series')
        original_build = build
        staged_files = {}
        for name, asset in p['source_binding']['staged_assets'].items():
            filename = asset['staged']
            require(Path(filename).name == filename, 'Flat exact staged asset')
            source = original_build / filename
            require(sha(source) == asset['sha256'], 'Original staged asset binding')
            target = execution_build / filename
            target.write_bytes(source.read_bytes())
            require(sha(target) == asset['sha256'], 'Byte-preserving execution staging')
            pins[str(target.relative_to(ROOT))] = sha(target)
            staged_files[filename] = asset['sha256']
        # Windows .bat argument handling split NAME=VALUE in the original
        # xvlog command. Put the exact macro in a source shim instead; do not
        # alter the frozen numerical testbench, backend, or golden assets.
        top = p['source_binding']['backend_top']
        require(re.fullmatch(r'z100_native_conv_backend_v\d+', top), 'Reviewed top identifier')
        argv0 = cmd['steps'][0]
        macro_at = argv0.index('-d')
        require(argv0[macro_at+1] == 'NATIVE_CONV_BACKEND_TOP=' + top, 'Exact original macro option')
        del argv0[macro_at:macro_at+2]
        require(Path(argv0[-1]).name == 'tb_z100_native_conv_first_event_v1.sv', 'Original testbench command seam')
        shim = execution_build / 'selected_backend_tb.sv'
        shim.write_text('`define NATIVE_CONV_BACKEND_TOP ' + top + '\n`include "tb_z100_native_conv_first_event_v1.sv"\n')
        pins[str(shim.relative_to(ROOT))] = sha(shim)
        argv0[-1] = str(shim)
        build = execution_build
        result.update(execution_build=str(build.relative_to(ROOT)), staged_asset_sha256=staged_files,
            command_correction='Source macro shim replaces Windows-batch-split -d NAME=VALUE; frozen TB/RTL/goldens unchanged.')
        expected = ['xvlog.bat', 'xelab.bat', 'xsim.bat']
        for argv, filename in zip(cmd['steps'], expected):
            require(Path(argv[0]).resolve() == Path('C:/appload/2026.1/Vivado/bin', filename).resolve(), 'Expected2026.1 vendor launcher')
            require(Path(argv[0]).is_file(), 'Installed vendor tool')
            pins['external/' + Path(argv[0]).as_posix().replace(':', '')] = sha(argv[0])
        pins[str(prepared.relative_to(ROOT))] = sha(prepared)
        pins[str(Path(__file__).relative_to(ROOT))] = sha(__file__)
        pins['tools/validate_z100_rom_prefetch_first_conv_v2.py'] = sha(ROOT / 'tools/validate_z100_rom_prefetch_first_conv_v2.py')
        result.update(status='PREFLIGHT_REAL_NUMERICAL_AFTER_LEGAL_ROUTE',
            prepared_report=str(prepared.relative_to(ROOT)),
            source_sha256_before=dict(pins), commands=[])
        save()
        print(json.dumps(dict(status=result['status'], report=str(report.relative_to(ROOT)))), flush=True)
        live = subprocess.run(['powershell', '-NoProfile', '-Command',
            "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(vivado|xsim)(\\.exe)?$' } | Select-Object ProcessId,Name | ConvertTo-Json -Compress"],
            text=True, capture_output=True, check=True)
        observed = json.loads(live.stdout) if live.stdout.strip() else []
        observed = observed if isinstance(observed, list) else [observed]
        require(not any(item['Name'].lower().startswith('vivado') for item in observed), 'Implementation priority: no competing Vivado flow')
        require(len(observed) <= 1, 'Maximum two actual logical vendor flows')
        for name, digest in pins.items():
            require(sha(repo_path(name)) == digest, 'Queued source drift: ' + name)
        for label, argv in zip(['xvlog', 'xelab', 'xsim'], cmd['steps']):
            log_path = out / (label + '.log')
            result['status'] = 'RUNNING_REAL_NATIVE_FIRST_CONV_' + label.upper()
            with log_path.open('w') as stream:
                child = subprocess.Popen(argv, cwd=build,
                    env=dict(os.environ, XILINX_LOCAL_USER_DATA='no', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1'),
                    stdout=stream, stderr=subprocess.STDOUT)
                entry = dict(label=label, args=argv, pid=child.pid)
                result['commands'].append(entry)
                save()
                print(json.dumps(dict(status=result['status'], pid=child.pid)), flush=True)
                entry['return_code'] = child.wait()
            log = log_path.read_text(errors='replace')
            require(entry['return_code'] == 0 and not re.search(r'^\s*(?:ERROR:|Fatal:)', log, re.M), 'Strict actual ' + label + ' diagnostics')
        markers = re.findall(r'^NATIVE_CONV_FIRST_EVENT_PASS .+$', log, re.M)
        require(len(markers) == 1, 'One complete real numerical marker')
        counts = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', markers[0])}
        expected_counts = dict(raw=102400, post=102400, packed=25600, source_R=209600, parameter_R=3712,
            output_W=204800, output_AW_B=12800, guards=57344)
        require(all(counts.get(k) == v for k, v in expected_counts.items()), 'Complete original C/OIHW/native DDR coverage')
        require(all(counts.get(k, 0) > 0 for k in ['held_AR', 'held_AW', 'held_W']), 'Actual held bus coverage')
        require('producer_complete=PHYSICAL_TILES_ONLY ledger_publication=NOT_CLAIMED' in markers[0], 'No fabricated graph publication')
        result.update(status='PASS_REAL_NATIVE_GUARDED_FIRST_CONV16_NUMERIC_NOT_FULLGRAPH', simulation=counts, marker=markers[0])
    except Exception as exc:
        result.update(status='FAILED_CLOSED', error=f'{type(exc).__name__}: {exc}')
    result['source_sha256_before'] = pins
    result['source_sha256_after'] = {name: sha(repo_path(name)) for name in pins}
    if pins != result['source_sha256_after']:
        result.update(status='FAILED_SOURCE_INTEGRITY', error='Pinned source changed')
    result['artifact_sha256'] = {str(path.relative_to(ROOT)): sha(path) for folder in [out, execution_build] for path in folder.rglob('*') if path.is_file() and path != report}
    save()
    print(json.dumps(dict(status=result['status'], report=str(report.relative_to(ROOT)), error=result.get('error'))), flush=True)
    return int(result['status'].startswith('FAILED'))


if __name__ == '__main__':
    raise SystemExit(main())
