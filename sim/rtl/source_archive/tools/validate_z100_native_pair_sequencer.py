"""All61 quality200 virtual tiles through actual resident-template sequencer."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, re, subprocess

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT/'deployment/hardware/z100_2026/native_pair_sequencer_v1'
VENDOR = Path('C:/appload/2026.1/Vivado/bin')
PLAN = ROOT/'validation/board_z100/native_pair_gather_plan/20261025T002753.768331Z/result.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(ok, message):
    if not ok:
        raise ValueError(message)


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out = ROOT/'validation/board_z100/native_pair_sequencer'/stamp
    build = ROOT/'build'/('psq_'+stamp[-14:])
    out.mkdir(parents=True); build.mkdir(parents=True)
    report = out/'result.json'
    result = dict(status='RUNNING', commands=[], board_access=False,
                  full_pipeline_30fps_accepted=False, production_integrated=False)
    before = {}
    try:
        p = json.loads(PLAN.read_text())
        check(p['status'].startswith('PASS_HOST_ALL61') and
              p['source_sha256_before'] == p['source_sha256_after'], 'Closed exact byte/template host plan')
        for n, h in {**p['source_sha256_after'], **p['artifact_sha256']}.items():
            check(sha(ROOT/n) == h, 'Host proof source/artifact drift '+n)
        manifest = ROOT/p['manifest']
        m = json.loads(manifest.read_text())
        rtl = [HW/'z100_native_pair_sequencer.sv', HW/'tb_z100_native_pair_sequencer.sv']
        before = {str(f.relative_to(ROOT)): sha(f) for f in [Path(__file__), PLAN, manifest, *rtl]}
        geometry, templates, expected = [], [], []
        for tile in m['tiles']:
            ts = tile['pair_templates']
            c, h, w = (tile[k] for k in ('channels', 'height', 'width'))
            epochs = {t['table_epoch'] for t in ts}
            check(len(epochs) == 1, 'Tile table epoch shared')
            te = epochs.pop()
            geometry.append(c | h << 10 | w << 20 | te << 30)
            for t in ts:
                templates.append(t['source_address'] | t['region_begin'] << 32 | t['region_end'] << 64 |
                                 t['source_generation'] << 97 | t['row_stride'] << 129 | t['x_stride'] << 161 |
                                 t['context'] << 193 | t['shift'] << 195)
            word = 0
            # Closed-form oracle; DUT instead updates separate per-template addresses.
            for c32 in range(0, c, 32):
                for y in range(h):
                    for x in range((w+15)//16):
                        for pair in range(min(4, (c-c32)//8)):
                            t = ts[c32//8+pair]
                            shift = t['shift']
                            address = t['source_address']+(y >> shift)*t['row_stride']+(x >> shift)*t['x_stride']
                            first_x = (x & ((1 << shift)-1))*(16 >> shift)
                            valid_x = min(16, w-x*16)
                            last = word+2 == tile['pair_operations']*2
                            expected.append(address | t['source_generation'] << 32 | t['context'] << 64 |
                                            shift << 66 | first_x << 68 | valid_x << 72 | word << 77 |
                                            int(last) << 89 | te << 90 | m['frame_epoch_fixture'] << 122)
                            word += 2
            check(word == tile['pair_operations']*2, 'Complete tile native command count')
        check(len(geometry) == 61 and len(templates) == 1032 and len(expected) == 68184,
              'Complete selected-model template coverage')
        for name, values, width in [('geometry', geometry, 16), ('templates', templates, 64), ('expected', expected, 40)]:
            (build/(name+'.hex')).write_text(''.join(f'{value:0{width}x}\n' for value in values))
        result.update(source_package_sha256=m['source_package_sha256'], source_sha256_before=before)
        report.write_text(json.dumps(result, indent=2)+'\n')

        def run(label, args):
            env = dict(os.environ, XILINX_LOCAL_USER_DATA='no')
            argv = list(map(str, args))
            proc = subprocess.run(argv, cwd=build, env=env, text=True,
                                  encoding='utf-8', errors='replace', stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout)
            result['commands'].append(dict(label=label, args=argv, return_code=proc.returncode))
            check(proc.returncode == 0 and not re.search(r'^\s*(?:ERROR:|Fatal:)', proc.stdout, re.M),
                  'Strict actual tool diagnostic '+label)
            return proc.stdout
        run('xvlog', [VENDOR/'xvlog.bat', '-sv', *rtl])
        run('xelab', [VENDOR/'xelab.bat', '-mt', '2', 'tb_z100_native_pair_sequencer', '-s', 'seq_sim'])
        logs = run('xsim', [VENDOR/'xsim.bat', 'seq_sim', '-runall'])
        markers = re.findall(r'^PAIR_SEQUENCER_PASS (.+)$', logs, re.M)
        check(len(markers) == 1, 'Unique complete simulation marker')
        sim = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', markers[0])}
        check(sim['tiles'] == 61 and sim['templates'] == 1032 and sim['requests'] == 68184 and
              sim['held_cycles'] > 0 and sim['rejected_cases'] == 12 and sim['blocked_clear_cycles'] == 96,
              'All real tile requests and negative guard coverage')
        result.update(status='PASS_PRIVATE_PAIR_SEQUENCER_ALL61_TILES1032_TEMPLATES68184_REQUESTS_XSIM_ONLY',
                      simulation=sim,
                      scope='Actual resident-template address/order/transform metadata dispatch with backpressure and12 negative cases. Host oracle already bound to exact source/LUT/nearest bytes. Cache/transform/store are not connected in this test; dispatch_done is not tile completion. No full graph, route or board performance acceptance.')
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
