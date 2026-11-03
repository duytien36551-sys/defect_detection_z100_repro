"""Actual all63-Conv halo inputs through one leased AXI burst/gather reader."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, re, shutil, subprocess

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT/'deployment/hardware/z100_2026'
VENDOR = Path('C:/appload/2026.1/Vivado/bin')
FIXTURE = ROOT/'validation/board_z100/quality200_halo_load_fixture4k_phase0/20261024T235944.102768Z/result.json'
BURST = ROOT/'validation/board_z100/materialized_load_review/20261024T153556.171212Z/result.json'
VIEWS = ROOT/'deployment/build/z100_quality200_virtual_views/20261024T134242.002345Z/views_manifest.json'
BASE = 0x10000000


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def check(ok, message):
    if not ok: raise ValueError(message)


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out = ROOT/'validation/board_z100/hybrid_ingress4k_v4'/stamp
    build = ROOT/'build'/('hyb_'+stamp[-14:])
    out.mkdir(parents=True); build.mkdir(parents=True); report = out/'result.json'
    rtl = [HW/n for n in (
        'native_materialized_load_v1/z100_native_materialized_load_control.sv',
        'native_stream_order_v1/z100_native_stream_order.sv',
        'native_view_gather_v1/z100_native_view_gather.sv',
        'native_view_context4_v1/z100_native_view_context4.sv',
        'native_word_cache_v1/z100_native_word_cache.sv',
        'native_axi64_reader_v1/z100_native_axi64_reader.sv',
        'native_ingress_reader_v2/z100_native_ingress_reader_v2.sv',
        'feature_banks_load_order_4k_v4/z100_feature_banks_load_order_4k_v4.sv')]
    tb = HW/'native_ingress_reader_v2/tb_z100_hybrid_ingress4k_v4.sv'
    sources = [Path(__file__), FIXTURE, BURST, VIEWS, tb, *rtl]; before = {}
    r = dict(status='RUNNING', commands=[], board_access=False, physical_deployed=False,
             fullgraph_execution_accepted=False, full_pipeline_30fps_accepted=False)
    try:
        fixture, burst = read(FIXTURE), read(BURST)
        check(fixture['status'].startswith('PASS_HOST_CURRENT200_ALL63') and burst['status'].startswith('ROOT_ACCEPT_CURRENT20042'), 'Closed actual input capture and burst prerequisites')
        for proof in (fixture, burst):
            if 'source_sha256_before' in proof:
                check(proof['source_sha256_before'] == proof['source_sha256_after'], 'Stable prerequisite sources')
            for key in ('source_sha256_after', 'source_sha256', 'artifact_sha256'):
                for n, h in proof.get(key, {}).items(): check(sha(ROOT/n) == h, 'Source/artifact prerequisite drift '+n)
            for binding in proof.get('report_bindings', {}).values():
                check(sha(ROOT/binding['path']) == binding['sha256'], 'Closed prerequisite report binding')
        prepared = ROOT/fixture['build']
        tiles_path = FIXTURE.parent/'halo_tiles.json'; regions_path = FIXTURE.parent/'source_regions.json'
        tiles, regions = read(tiles_path), read(regions_path)
        virtual = {v['node'] for v in read(VIEWS)['virtual_nodes']}
        names = ('source.hex','words.hex','descriptors.hex','tables.hex','counts.hex','node_geometry.hex','fixture_defs.vh')
        sources += [tiles_path, regions_path, *(prepared/n for n in names)]
        before = {str(p.relative_to(ROOT)): sha(p) for p in sources}
        for name in names: shutil.copy2(prepared/name, build/name)
        descs = [int(x, 16) for x in (prepared/'descriptors.hex').read_text().split()]
        words = [int(x, 16) for x in (prepared/'words.hex').read_text().split()]
        cases = []; ars = []; tags = {}; cursor = 0
        stats = dict(materialized_tiles=0,virtual_tiles=0,materialized_words=0,virtual_words=0,
                     burst_commands=0,virtual_descriptors=0,hits=0,misses=0,AXI_R=0)
        for tile in tiles:
            kind = tile['input_node'] in virtual
            sr = regions[str(tile['input_node'])] if not kind else None
            c,h,w,y,n = (tile[k] for k in ('input_channels','input_rows','input_width','input_y','words'))
            address = BASE+sr['start']*64 if sr else 0
            full_h = sr['height'] if sr else 0
            cases.append(address|(c<<32)|(full_h<<43)|(w<<53)|(y<<63)|(h<<73)|(n<<83)|(tile['word_offset']<<97)|(int(kind)<<129))
            count = (c+3)//4
            ds = descs[cursor:cursor+count]; cursor += count
            if kind:
                stats['virtual_tiles'] += 1; stats['virtual_words'] += n; stats['virtual_descriptors'] += count
                wi = tile['word_offset']
                for d in ds:
                    generation = (((d>>32)&0xffffffff)>>6)+1
                    for word in words[wi:wi+((d>>251)&65535)]:
                        a = (word>>512)&0xffffffff; index = (a>>6)&511; key = (200,generation,a>>15)
                        if tags.get(index) == key: stats['hits'] += 1
                        else:
                            stats['misses'] += 1; tags[index] = key; ars.append(a|(7<<32)); stats['AXI_R'] += 8
                    wi += (d>>251)&65535
                check(wi == tile['word_offset']+n, 'Every virtual source word covered')
            else:
                stats['materialized_tiles'] += 1; stats['materialized_words'] += n
                check(sr['channels']==c and sr['width']==w and y+h<=full_h, 'Full materialized source geometry')
                group_base=sr['start']; xwords=(w+15)//16
                for c32 in range(0,c,32):
                    subgroups=(min(32,c-c32)+3)//4
                    a=BASE+(group_base+y*xwords*subgroups)*64; remaining=h*xwords*subgroups*8
                    stats['burst_commands'] += 1
                    while remaining:
                        beats=min(16,remaining,(4096-(a&4095))//8)
                        check(beats>0, 'Positive page-bounded materialized burst')
                        ars.append(a|((beats-1)<<32)); stats['AXI_R'] += beats; a+=beats*8; remaining-=beats
                    group_base+=subgroups*full_h*xwords
        check(cursor==3808 and len(tiles)==189 and stats['materialized_tiles']==128 and stats['virtual_tiles']==61 and
              stats['materialized_words']==211496 and stats['virtual_words']==136368 and stats['burst_commands']==240, 'All63 admitted input tiles')
        for name,values,width in [('hybrid_cases.hex',cases,33),('hybrid_ar.hex',ars,9)]:
            (build/name).write_text(''.join(f'{v:0{width}x}\n' for v in values))
        with (build/'fixture_defs.vh').open('a') as f:
            for name,value in dict(HYBRID_ARS=len(ars),HYBRID_R=stats['AXI_R'],VIRTUAL_DESCRIPTORS=stats['virtual_descriptors'],HYBRID_HITS=stats['hits'],HYBRID_MISSES=stats['misses']).items():
                f.write(f'`define {name} {value}\n')
        r.update(source_package_sha256=fixture['source_package_sha256'],fixture=stats|dict(AXI_AR=len(ars),layers=63,tiles=189,words=347864))
        report.write_text(json.dumps(r,indent=2)+'\n')
        def run(label,args):
            env=dict(os.environ); env['XILINX_LOCAL_USER_DATA']='no'
            for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'): env[k]='1'
            argv=list(map(str,args)); proc=subprocess.run(argv,cwd=build,env=env,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(label+'.log')).write_text(proc.stdout); r['commands'].append(dict(label=label,args=argv,return_code=proc.returncode))
            check(proc.returncode==0 and not re.search(r'^\s*(?:ERROR:|Fatal:)',proc.stdout,re.M), 'Strict actual tool diagnostic '+label)
            return proc.stdout
        run('xvlog',[VENDOR/'xvlog.bat','-sv',*rtl,tb])
        run('xelab',[VENDOR/'xelab.bat','-mt','2','tb_z100_hybrid_ingress4k_v4','-s','hybrid_sim'])
        logs=run('xsim',[VENDOR/'xsim.bat','hybrid_sim','-runall'])
        marker=re.findall(r'^HYBRID_INGRESS_PASS (.+)$',logs,re.M); check(len(marker)==1,'Complete actual all63 hybrid ingress marker')
        sim={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',marker[0])}
        expected=dict(layers=63,tiles=189,words=347864,readback=347864,burst_commands=240,virtual_descriptors=stats['virtual_descriptors'],logical_virtual_reads=136368,
                      AXI_AR=len(ars),AXI_R=stats['AXI_R'],hits=stats['hits'],misses=stats['misses'],leases=189,recoveries=2,release_blocked=24)
        check(all(sim[k]==v for k,v in expected.items()) and all(sim[k]>0 for k in ('drain_probes','wrong_owner_probes','stalls')), 'Actual mixed path/lease/drain/reader/store coverage')
        r.update(status='PASS_PRIVATE_4K_V4_RELEASE_GUARD_ALL63_HYBRID_BURST_CACHED_GATHER_ONE_LEASED_AXI_READER_REAL_RAM_XSIM_ONLY',simulation=sim,
            scope='One frozen reader,128 materialized burst tiles and58 virtual gather tiles,347864 checked actual RAM words. Lease mode survives command-pin changes, excludes non-owner commands/cancel/clear and blocks release through held-AR abort/drain in both paths. Host drives tile/descriptor order. No63-MAC execution, ping-pong compute coupling, fullgraph branch/ADD lifetime, HP platform, frequency or physical FPS acceptance.')
    except Exception as exc: r.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    r['source_sha256_before']=before; r['source_sha256_after']={n:sha(ROOT/n) for n in before}
    if before!=r['source_sha256_after']: r.update(status='FAILED_SOURCE_INTEGRITY',error='Source drift')
    r['artifact_sha256']={str(f.relative_to(ROOT)):sha(f) for folder in (out,build) for f in folder.rglob('*') if f.is_file() and f!=report}
    report.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))))
    return int(r['status'].startswith('FAILED'))


if __name__=='__main__': raise SystemExit(main())
