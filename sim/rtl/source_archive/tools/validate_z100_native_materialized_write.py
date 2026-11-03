"""Reserved native DDR tile writeback with exact codec and actual AXI writer."""
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
    out = ROOT/'validation/board_z100/native_materialized_write'/stamp
    build = ROOT/'build'/('mw_'+stamp[-14:])
    out.mkdir(parents=True); build.mkdir(parents=True)
    report = out/'result.json'
    rtl = [HW/name for name in (
        'native_stream_order_v1/z100_native_stream_order.sv',
        'native_axi64_writer_v1/z100_native_axi64_writer.sv',
        'native_materialized_write_v1/z100_native_materialized_write_control.sv',
        'native_materialized_write_v1/tb_z100_native_materialized_write.sv')]

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
        run('xelab', [VENDOR/'xelab.bat', '-mt', '2', 'tb_z100_native_materialized_write', '-s', 'pair_sim'])
        logs = run('xsim', [VENDOR/'xsim.bat', 'pair_sim', '-runall'])
        markers = re.findall(r'^MATERIALIZED_WRITE_PASS (.+)$', logs, re.M)
        check(len(markers) == 1, 'Unique complete simulation marker')
        sim = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', markers[0])}
        check(sim['successful_tiles']==9 and sim['verified_DDR_beats']>300000 and
              sim['recoveries']==17 and sim['drain_checks']==90 and sim['AXI_AW']>100 and
              sim['AXI_W']>40000 and sim['AXI_B']>100 and sim['premature_commit_checks']>0,
              'Actual native scatter, tail/page/row bounds, B-completion, ownership and recovery coverage')
        result.update(status='PASS_PRIVATE_RESERVED_NATIVE_TILE_WRITEBACK_CODEC_REAL_AXI_WRITER_DDR_CONTENT_RECOVERY_XSIM_ONLY',
                      simulation=sim,
                      scope='Nine successful row tiles, full DDR contents including untouched rows/padding,8 geometries up to512 channels/4096 tile words and1024-channel tail blocks; ten bad reservations, AW/W/B cancellation with90 blocked clear cycles, timeout, BID/BRESP and codec metadata faults. tile_committed follows all B responses and codec retirement. Full-tensor publication, actual compute/ADD output, HP integration, synthesis/route and physical FPS remain unaccepted.')
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
