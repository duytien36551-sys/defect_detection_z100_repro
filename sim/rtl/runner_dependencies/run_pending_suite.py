"""Run the five prepared counter checks serially; never retry a failed tool."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import resume_prepared_sim as resume

ROOT = Path(__file__).resolve().parent
RECIPES = [('pool_fault_resume', 'regressions01/pool_fault/actual_run_command.json'),
           ('unit', 'unit02/run_command.json'),
           ('id_fault', 'regressions01/id_fault/run_command.json'),
           ('mixed_diagnostics', 'mixed_diagnostics02/run_command.json'),
           ('fault_diagnostics', 'fault_diagnostics02/run_command.json')]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def prepare():
    hashes = {}
    jobs = []
    for role, relative in RECIPES:
        recipe = ROOT / relative
        value = json.loads(recipe.read_text())
        argv = value['argv'] if isinstance(value, dict) else value
        run = ROOT / 'validation' / argv[argv.index('--run-id') + 1]
        marker = argv[argv.index('--pass-marker') + 1]
        paths = [recipe]
        for index, arg in enumerate(argv):
            if arg in ['--dut', '--extra-source', '--testbench']:
                paths.append(Path(argv[index + 1]))
            if arg == '--fixtures':
                paths.extend(p for p in Path(argv[index + 1]).iterdir()
                             if p.suffix in ['.hex', '.vh', '.mem'])
        if role == 'pool_fault_resume':
            resume.preflight(run, recipe)
            result = run / 'resume_xsim_result.json'
            argv = [sys.executable, '-X', 'utf8', '-B', str(ROOT / 'resume_prepared_sim.py'),
                    '--run', str(run), '--command', str(recipe)]
            paths.extend([run / 'result.json', run / 'compiled_snapshot_manifest.json'])
        else:
            require(not run.exists(), 'Run already exists; inspect, never retry: ' + str(run))
            result = run / 'result.json'
        for path in paths:
            hashes[str(path)] = sha(path)
        jobs.append({'role': role, 'argv': argv, 'result': str(result), 'pass_marker': marker})
    for path in [Path(__file__), ROOT / 'run_sim.py', ROOT / 'resume_prepared_sim.py',
                 Path('C:/z100v13/gpt_pl_view_ingress01/run_lut_unit.py')]:
        hashes[str(path)] = sha(path)
    return {'status': 'PREPARED_NO_VENDOR_NO_BOARD', 'jobs': jobs, 'input_sha256': hashes,
            'resource_gate': {'free_ram_gib': 8, 'free_disk_gib': 20, 'vendor_idle': True},
            'stop_policy': 'First nonzero exit, missing evidence, source drift or failed result stops the suite.',
            'board_access': False}


def verify_hashes(hashes):
    for name, digest in hashes.items():
        require(sha(Path(name)) == digest, 'Frozen input changed: ' + name)


def verify_result(job):
    path = Path(job['result'])
    result = json.loads(path.read_text())
    require(result['status'].startswith('PASS_') and
            job['pass_marker'] in result.get('pass_line', ''), 'Simulation not passed: ' + str(path))
    require(len(result['commands']) == 3 and
            all(c['returncode'] == 0 for c in result['commands']), 'Incomplete vendor stages')
    for name, digest in result['staged_inputs_sha256'].items():
        require(sha(path.parent / name) == digest, 'Staged input drift: ' + name)
    for source in result['sources']:
        source = Path(source)
        require(source.read_bytes() == (path.parent / source.name).read_bytes(), 'Source drift: ' + str(source))
    return {'path': str(path), 'sha256': sha(path), 'pass_line': result['pass_line']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.prepare_only:
        require(not args.plan.exists(), 'Preserve previous plan')
        args.plan.write_text(json.dumps(prepare(), indent=2))
        print('PASS_PENDING_SUITE_PREPARED jobs=5 vendor=false board=false')
        return
    plan = json.loads(args.plan.read_text())
    require(plan['status'] == 'PREPARED_NO_VENDOR_NO_BOARD', 'Unexpected plan')
    verify_hashes(plan['input_sha256'])
    require(prepare()['jobs'] == plan['jobs'], 'Pending job identity changed')
    require(args.output is not None and not args.output.exists(), 'Fresh output required')
    # Child executors acquire the shared vendor mutex and recheck admission.
    # This read-only precheck avoids consuming a run directory when already blocked.
    admission = resume.inspect_host()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'RUNNING', 'plan_sha256': sha(args.plan), 'admission': admission,
              'jobs': [], 'board_access': False}
    report_path = args.output / 'result.json'

    def save():
        report_path.write_text(json.dumps(report, indent=2))

    save()
    try:
        for job in plan['jobs']:
            verify_hashes(plan['input_sha256'])
            resume.inspect_host()
            row = {'role': job['role'], 'started': time.time(), 'argv': job['argv']}
            report['jobs'].append(row)
            save()
            with (args.output / (job['role'] + '.log')).open('wb') as log:
                proc = subprocess.Popen(job['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                        creationflags=subprocess.CREATE_NO_WINDOW,
                                        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1'))
                row['pid'] = proc.pid
                save()
                row['returncode'] = proc.wait()
            row['seconds'] = time.time() - row['started']
            require(row['returncode'] == 0, 'First failure: ' + job['role'])
            row['evidence'] = verify_result(job)
            save()
        verify_hashes(plan['input_sha256'])
        report['status'] = 'PASS_FIVE_SIMULATIONS_PLATFORM_REVIEW_PENDING'
    except Exception as exc:
        report.update(status='STOPPED_NO_AUTORETRY', error=str(exc))
        raise
    finally:
        save()
    print(report['status'])


if __name__ == '__main__':
    main()
