"""Serial frozen regressions for the passive T+1 diagnostic publication fix."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
PRIOR = Path('C:/z100v13/gpt_acp_counter_integration01')
OLD_RTL = Path('C:/z100v13/gpt_acp_phase_counters01/overrides/rtl')
sys.path.insert(0, str(PRIOR))
from run_pending_suite import verify_result

sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
recipes = [
    ('fault_diagnostics', 'fault_diagnostics03/run_command.json'),
    ('mixed_diagnostics', 'mixed_diagnostics02/run_command.json'),
    ('control', 'regressions01/control/actual_run_command.json'),
    ('tail', 'regressions01/tail/actual_run_command.json'),
    ('pool_control', 'regressions01/poolctl/actual_run_command.json'),
    ('mixed', 'regressions01/mixed/actual_run_command.json'),
    ('pool_fault', 'regressions01/pool_fault/actual_run_command.json'),
    ('id_fault', 'regressions01/id_fault/run_command.json'),
]

def make_plan():
    jobs, hashes = [], {}
    for role, relative in recipes:
        recipe = PRIOR / relative
        args = json.loads(recipe.read_text())
        if isinstance(args, dict):
            args = args['argv']
        args = [str(ROOT / 'run_sim.py') if x == str(PRIOR / 'run_sim.py')
                else str(ROOT / 'rtl' / Path(x).name) if Path(x).parent == OLD_RTL
                else x for x in args]
        args[args.index('--run-id') + 1] = role + '01'
        if role == 'fault_diagnostics':
            args[args.index('--testbench') + 1] = str(ROOT / 'fault_tb.sv')
        result = ROOT / 'validation' / (role + '01') / 'result.json'
        assert not result.parent.exists(), str(result)
        paths = [recipe, ROOT / 'run_sim.py', Path(__file__)]
        for i, arg in enumerate(args):
            if arg in ['--dut', '--extra-source', '--testbench']:
                paths.append(Path(args[i + 1]))
            elif arg == '--fixtures':
                paths.extend(p for p in Path(args[i + 1]).iterdir() if p.suffix in ['.hex', '.mem', '.vh'])
        hashes.update({str(p): sha(p) for p in paths})
        jobs.append({'role': role, 'argv': args, 'result': str(result),
                     'pass_marker': args[args.index('--pass-marker') + 1]})
    return {'jobs': jobs, 'sha256': hashes, 'board_access': False}

def main():
    plan_path = ROOT / 'regression_plan.json'
    result_path = ROOT / 'regression_result.json'
    assert not result_path.exists(), 'No automatic retries'
    plan = make_plan()
    plan_path.write_text(json.dumps(plan, indent=2))
    report = {'status': 'RUNNING', 'plan_sha256': sha(plan_path), 'jobs': [], 'board_access': False}
    save = lambda: result_path.write_text(json.dumps(report, indent=2))
    def frozen():
        for name, digest in plan['sha256'].items():
            assert sha(Path(name)) == digest, name
    save()
    try:
        frozen()
        for job in plan['jobs']:
            frozen()
            row = {'role': job['role'], 'started': time.time(), 'argv': job['argv']}
            report['jobs'].append(row)
            save()
            with (ROOT / (job['role'] + '.log')).open('wb') as log:
                process = subprocess.Popen(job['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NO_WINDOW,
                                           env=dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1'))
                row['pid'] = process.pid
                save()
                row['returncode'] = process.wait()
            row['seconds'] = time.time() - row['started']
            assert row['returncode'] == 0, 'First failure: ' + job['role']
            row['evidence'] = verify_result(job)
            save()
        frozen()
        report['status'] = 'PASS_EIGHT_REGRESSIONS_PRIMARY_REVIEW_PENDING'
    except Exception as exc:
        report.update(status='STOPPED_NO_AUTORETRY', error=str(exc))
        raise
    finally:
        save()
    print(report['status'])

if __name__ == '__main__':
    main()
