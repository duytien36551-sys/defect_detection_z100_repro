"""Actual pair pipeline through native address conversion and checked4K RAM readback."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, re, shutil, subprocess

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT/'deployment/hardware/z100_2026'
VENDOR = Path('C:/appload/2026.1/Vivado/bin')
SEQ = ROOT/'validation/board_z100/native_pair_sequencer/20261025T042156.409518Z/result.json'
FIXTURE = ROOT/'validation/board_z100/quality200_halo_load_fixture4k_phase0/20261024T235944.102768Z/result.json'
PLAN = ROOT/'validation/board_z100/native_pair_gather_plan/20261025T002753.768331Z/result.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(ok, message):
    if not ok:
        raise ValueError(message)


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out = ROOT/'validation/board_z100/native_pair_feature_ram'/stamp
    build = ROOT/'build'/('pfr_'+stamp[-14:])
    out.mkdir(parents=True); build.mkdir(parents=True)
    report = out/'result.json'
    result = dict(status='RUNNING', commands=[], board_access=False,
                  full_pipeline_30fps_accepted=False, production_integrated=False)
    before = {}
    try:
        proofs = [json.loads(f.read_text()) for f in (SEQ, FIXTURE, PLAN)]
        for p in proofs:
            check(p['status'].startswith('PASS_') and p['source_sha256_before'] == p['source_sha256_after'], 'Closed fixture proof')
            for n, h in {**p['source_sha256_after'], **p['artifact_sha256']}.items():
                check(sha(ROOT/n) == h, 'Fixture source/artifact drift '+n)
        seq, fixture, plan = proofs
        for name in ('geometry.hex', 'templates.hex'):
            candidates = [ROOT/n for n in seq['artifact_sha256'] if Path(n).name == name]
            check(len(candidates) == 1, 'Unique closed sequencer fixture '+name)
            shutil.copyfile(candidates[0], build/name)
        manifest = ROOT/plan['manifest']
        m = json.loads(manifest.read_text())
        fixture_build = ROOT/fixture['build']
        halo_path = FIXTURE.parent/'halo_tiles.json'
        halos = {t['tile']: t for t in json.loads(halo_path.read_text())}
        words_path = fixture_build/'words.hex'
        table_path = fixture_build/'tables.hex'
        source_path = fixture_build/'source.hex'
        words = [int(x, 16) for x in words_path.read_text().split()]
        tables = table_path.read_text().split()
        golden, selected_tables = [], []
        for tile in m['tiles']:
            original = halos[tile['tile']]
            c, h, w = (tile[k] for k in ('channels', 'height', 'width'))
            xwords = (w+15)//16
            native_word = 0
            for c32 in range(0, c, 32):
                for y in range(h):
                    for x in range(xwords):
                        for subgroup in range(min(8, (c-c32)//4)):
                            canonical = ((c32//4+subgroup)*h+y)*xwords+x
                            payload = words[original['word_offset']+canonical] & ((1 << 512)-1)
                            last = native_word+1 == original['words']
                            golden.append(payload | native_word << 512 | int(last) << 524 | 200 << 525)
                            native_word += 1
            check(native_word == original['words'], 'Full native word order')
            selected_tables.extend(tables[tile['tile']*1024:(tile['tile']+1)*1024])
        check(len(golden) == 136368 and len(selected_tables) == 61*1024, 'All virtual source bytes')
        (build/'expected_words.hex').write_text(''.join(f'{v:0140x}\n' for v in golden))
        (build/'tables.hex').write_text('\n'.join(selected_tables)+'\n')
        shutil.copyfile(source_path, build/'source.hex')
        memwords = len(source_path.read_text().split())
        (build/'fixture_defs.vh').write_text(f'`define MEMWORDS {memwords}\n')
        rtl = [HW/n for n in (
            'native_pair_sequencer_v1/z100_native_pair_sequencer.sv',
            'native_pair_cache_v1/z100_native_pair_cache.sv',
            'native_axi64_reader_v1/z100_native_axi64_reader.sv',
            'native_view_context4_v1/z100_native_view_context4.sv',
            'native_pair_transform_v1/z100_native_pair_transform.sv',
            'native_feature_address_v1/z100_native_feature_address.sv',
            'feature_banks_load_order_4k_v4/z100_feature_banks_load_order_4k_v4.sv')]
        original_tb=HW/'native_pair_transform_v1/tb_z100_native_pair_pipeline.sv'
        seam=ROOT/'tools/z100_pair_feature_ram_tb.py'
        import sys
        sys.path.insert(0,str(ROOT/'tools'))
        from z100_pair_feature_ram_tb import instrument
        tb=build/'tb_z100_native_pair_feature_ram.sv'
        tb.write_text(instrument(original_tb.read_text()))
        rtl.append(tb)
        before = {str(f.relative_to(ROOT)): sha(f) for f in [Path(__file__), SEQ, FIXTURE, PLAN, manifest, halo_path,
                                                           words_path, table_path, source_path, original_tb, seam, *rtl]}
        result.update(source_sha256_before=before, source_package_sha256=fixture['source_package_sha256'])
        report.write_text(json.dumps(result, indent=2)+'\n')

        def run(label, args):
            env = dict(os.environ, XILINX_LOCAL_USER_DATA='no')
            argv = list(map(str, args))
            proc = subprocess.run(argv, cwd=build, env=env, text=True, encoding='utf-8', errors='replace',
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout)
            result['commands'].append(dict(label=label, args=argv, return_code=proc.returncode))
            check(proc.returncode == 0 and not re.search(r'^\s*(?:ERROR:|Fatal:)', proc.stdout, re.M), 'Strict actual tool diagnostic '+label)
            return proc.stdout
        run('xvlog', [VENDOR/'xvlog.bat', '-sv', *rtl])
        run('xelab', [VENDOR/'xelab.bat', '-mt', '2', 'tb_z100_native_pair_feature_ram', '-s', 'pipeline_sim'])
        logs = run('xsim', [VENDOR/'xsim.bat', 'pipeline_sim', '-runall'])
        markers = re.findall(r'^PAIR_FEATURE_RAM_PASS (.+)$', logs, re.M)
        check(len(markers) == 1, 'Complete actual pipeline marker')
        sim = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', markers[0])}
        check(all(sim[k] == v for k, v in dict(tiles=61, words=136368, pair_requests=68184,
                  AXI_AR=60624, AXI_R=969984, hits=7560, misses=60624, recoveries=4, drain_checks=80).items())
              and sim['readback_words']==136368 and sim['ram_commits']==61 and sim['active_cycles'] > 0 and sim['output_hold_cycles'] > 0, 'Exact payload, ownership, transport and fault coverage')
        result.update(status='PASS_PRIVATE_PAIR_PIPELINE_ALL61_HALOS_CHECKED4K_RAM136368WORDS_COMMIT_READBACK_XSIM_ONLY',
                      simulation=sim,
                      scope='Actual sequencer+pair cache+frozen AXI reader+exact context4 transform, all61 virtual halos output compared to closed integer capture. Four integrated fault/cancel cases. Writes checked4K feature RAM with canonical address conversion and full readback; does not connect shared ingress lease/mixed materialized path/compute; no fullgraph/HP/physical FPS acceptance.',
                      cycle_scope='Sum start-to-last-output completion across61 tiles, excludes palette/template configuration; periodic AR/R producer gaps and output stalls. Legal registered R producer differs from old per-beat model; no direct latency percentage or physical timing claim.')
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
