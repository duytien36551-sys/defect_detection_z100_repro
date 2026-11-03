"""Actual128B atomic cache + frozen AXI reader, faults, ownership and recovery."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, re, subprocess

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT/'deployment/hardware/z100_2026'
VENDOR = Path('C:/appload/2026.1/Vivado/bin')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(ok, message):
    if not ok:
        raise ValueError(message)


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out = ROOT/'validation/board_z100/native_pair_cache256k'/stamp
    build = ROOT/'build'/('pc256_'+stamp[-14:])
    out.mkdir(parents=True); build.mkdir(parents=True)
    report = out/'result.json'
    rtl = [HW/name for name in (
        'native_axi64_reader_v1/z100_native_axi64_reader.sv',
        'native_pair_cache_v2/z100_native_pair_cache_v2.sv',
        'native_pair_cache_v2/tb_z100_native_pair_cache_v2.sv')]
    before = {str(p.relative_to(ROOT)): sha(p) for p in [Path(__file__), *rtl]}
    result = dict(status='RUNNING', commands=[], board_access=False,
                  full_pipeline_30fps_accepted=False, production_integrated=False)
    report.write_text(json.dumps(result, indent=2)+'\n')
    try:
        def run(label, args):
            env = dict(os.environ, XILINX_LOCAL_USER_DATA='no')
            argv = list(map(str, args))
            proc = subprocess.run(argv, cwd=build, env=env, text=True,
                                  encoding='utf-8', errors='replace',
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout)
            result['commands'].append(dict(label=label, args=argv, return_code=proc.returncode))
            check(proc.returncode == 0 and not re.search(r'^\s*(?:ERROR:|Fatal:)', proc.stdout, re.M),
                  'Strict actual tool diagnostic '+label)
            return proc.stdout
        run('xvlog', [VENDOR/'xvlog.bat', '-sv', *rtl])
        run('xelab', [VENDOR/'xelab.bat', '-mt', '2', 'tb_z100_native_pair_cache_v2', '-s', 'pair_sim'])
        logs = run('xsim', [VENDOR/'xsim.bat', 'pair_sim', '-runall'])
        markers = re.findall(r'^PAIR_CACHE256K_PASS (.+)$', logs, re.M)
        check(len(markers) == 1, 'Unique complete simulation marker')
        sim = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', markers[0])}
        check(sim['atomic_preserves'] == 13 and sim['blocked_clear_cycles'] == 140 and
              sim['recoveries'] == 18 and sim['errors'] == 16 and sim['checks'] > 17000 and
              sim['held_cycles'] > 14700 and sim['ar'] > 2100 and sim['hits'] >= 18,
              'Numeric, capacity, source identity, fault and drain coverage')
        result.update(status='PASS_PRIVATE_PAIR256K_CACHE_FROZEN_AXI_READER_ATOMIC_FILL_RECOVERY_XSIM_ONLY',
                      simulation=sim,
                      scope='All128 bytes independently checked; >one cache capacity; generation/epoch/address alias; page end; output hold and command pin mutation. Six private metadata faults, four physical AXI faults, four bad commands, first-word cancel, held-AR and absent-R drain barriers, cancelled held output. No hardware pair sequencer, whole graph, synthesis resource or board performance acceptance.')
    except Exception as exc:
        result.update(status='FAILED_CLOSED', error=f'{type(exc).__name__}: {exc}')
    result['source_sha256_before'] = before
    result['source_sha256_after'] = {n: sha(ROOT/n) for n in before}
    if before != result['source_sha256_after']:
        result.update(status='FAILED_SOURCE_INTEGRITY', error='Source drift')
    result['artifact_sha256'] = {str(p.relative_to(ROOT)): sha(p) for folder in (out, build)
                                 for p in folder.rglob('*') if p.is_file() and p != report}
    report.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(status=result['status'], report=str(report), error=result.get('error'))))
    return int(result['status'].startswith('FAILED'))


if __name__ == '__main__':
    raise SystemExit(main())
