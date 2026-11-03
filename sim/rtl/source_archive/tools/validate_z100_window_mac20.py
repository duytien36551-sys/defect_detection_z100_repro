"""Exact20site packed/feedback MAC: independent OIHW/NCHW and numeric stress."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import argparse,hashlib,importlib.util,json,re,shutil

ROOT=Path(__file__).resolve().parents[1]
HW=ROOT/'deployment/hardware/z100_2026/window_mac20_v1'
CORE=HW/'z100_window_mac.sv';TB=HW/'tb_z100_window_mac20.sv'
ACC=ROOT/'deployment/hardware/z100_2026/accum33_dsp_v2/z100_accum33_dsp.sv'
FEEDBACK=ROOT/'deployment/hardware/z100_2026/window_mac_packed_feedback_v1/z100_window_mac.sv'
PROOF=ROOT/'validation/board_z100/packed_feedback/20261024T081043.248930Z/result.json'
HELPER=ROOT/'tools/validate_z100_window_mac_packed.py'


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def require(ok,message):
    if not ok:raise ValueError(message)


def make_fixture(scale,build,model):
    report=scale.create_firstconv_fixture(build,model)
    points=list(scale.PIXELS)+[(0,1),(0,318),(319,1),(319,318),(1,0),(1,319),(160,160),(100,100)]
    require(len(points)==20,'20 distinct reference coordinates')
    payload=model['payload'];desc=model['descriptor'];nchw=scale.NCHW_INPUT.read_bytes()
    bias=[int.from_bytes(payload[desc['bias']+lane*4:desc['bias']+lane*4+4],'little',signed=True)
          if lane<16 else 0 for lane in range(32)]
    act=[0]*(9*4*20);expected=[0]*(20*32)
    signed=lambda x:x-256 if x>127 else x
    for site,(oy,ox) in enumerate(points):
        sums=list(bias)
        for ky in range(3):
            for kx in range(3):
                iy=oy*2+ky-1;ix=ox*2+kx-1;group=ky*3+kx
                for channel in range(4):
                    v=signed(nchw[(channel*640+iy)*640+ix]) if channel<3 and 0<=iy<640 and 0<=ix<640 else 0
                    act[(group*4+channel)*20+site]=v&255
                    if channel<3:
                        for lane in range(16):
                            weight=signed(payload[desc['weight']+((lane*3+channel)*3+ky)*3+kx])
                            sums[lane]+=v*weight
        require(all(-(1<<31)<=v<(1<<31) for v in sums),'20site real reference overflow')
        for lane,v in enumerate(sums):expected[site*32+lane]=v&0xffffffff
    scale.write_hex(build/'fixture/firstconv_activations.hex',act,2)
    scale.write_hex(build/'fixture/firstconv_expected.hex',expected,8)
    report['direct20_coordinates']=points
    report['generated_fixture']={p.name:dict(bytes=p.stat().st_size,sha256=sha(p)) for p in (build/'fixture').iterdir()}
    report['oracle']='Direct original OIHW and signed NCHW20selected positions; no packed multiplication reference'
    return report


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--execute',action='store_true');args=ap.parse_args()
    spec=importlib.util.spec_from_file_location('packed20_helper',HELPER);h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
    scale=h.load_scale()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/mac20'/stamp;build=ROOT/'deployment/build/mac20'/stamp
    out.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    paths=tuple(dict.fromkeys([*h.paths(scale),CORE,TB,ACC,FEEDBACK,PROOF,Path(__file__)]))
    before={h.rel(p):sha(p) for p in paths};d=dict(status='RUNNING',source_sha256_before=before,
        commands=[],board_access=False,production_integrated=False,full_pipeline_30fps_accepted=False)
    report=out/'result.json'
    try:
        pr=json.loads(PROOF.read_text())
        require(pr['status']=='PASS_PRIVATE_PACKED_FEEDBACK_XSIM_OOC_ONLY','12site feedback prerequisite')
        require(pr['synthesis']['DSP_modes']==dict(MULTIPLY=768,NONE=384),'12site mapping prerequisite')
        for name,value in pr['source_sha256_after'].items():
            parts=Path(name).parts;p=Path(parts[1]+':/',*parts[2:]) if parts[0]=='external' else ROOT/name
            require(sha(p)==value,'Prerequisite source drift '+name)
        expected=FEEDBACK.read_text().replace('parameter integer SITES=4','parameter integer SITES=20')
        expected=expected.replace('input wire [3:0] run_sites','input wire [4:0] run_sites').replace(
            'output wire [3:0] out_site','output wire [4:0] out_site').replace('reg [3:0] sites, drain_site','reg [4:0] sites, drain_site')
        require(CORE.read_text()==expected,'20site only supported dimension/field delta')
        require('jobs != 24' in TB.read_text() and 'word_checks != 7424' in TB.read_text() and
            'site_index=15;site_index<=16' in TB.read_text(),'20site independent5bit boundary coverage')
        h.snapshot(paths,out/'src');d['fixture']=make_fixture(scale,build,scale.validate_model_inputs())
        d['status']='PASS_PRIVATE_20SITE_MAC_HOST_ONLY'
        if args.execute:
            h.run('xvlog',[h.VIVADO/'xvlog.bat','-sv',CORE,h.PAIR,ACC,TB,h.GLBL],build,out,d)
            h.run('xelab',[h.VIVADO/'xelab.bat','-mt','2','-L','unimacro_ver','-L','unisims_ver',
                'tb_z100_window_mac20','glbl','-s','mac20_sim'],build,out,d)
            text=h.run('xsim',[h.VIVADO/'xsim.bat','mac20_sim','-runall'],build,out,d)
            rows=re.findall(r'^WINDOW_MAC20_PASS ([^\r\n]+)$',text,re.M)
            require(len(rows)==1,'20site unique numeric PASS marker')
            v={k:int(x) for k,x in re.findall(r'(\w+)=(\d+)',rows[0])}
            exact=dict(sites20_jobs=24,sites20_words=7424,sites20_metadata=232,
                sites20_stream_errors=3,sites20_config_errors=6,sites20_run_errors=6,
                sites20_cross=1280,sites20_saturation=1280,sites20_cancel_offsets=5,
                sites20_reset_offsets=5,sites20_real_windows=40,sites20_site_tail_mask=109,
                sites20_lane_tail_mask=15,sites20_group_mask=31,max_groups=1024)
            require(all(v.get(k)==x for k,x in exact.items()) and v['replays']>=2 and
                v['sites20_stalls']>0 and v['sites20_bubbles']>0,'20site numeric coverage')
            d['simulation']=v
            h.CORE=CORE;tcl=h.write_tcl(out,build);text=tcl.read_text()
            text=text.replace('read_verilog -sv '+h.brace(h.PAIR)+' '+h.brace(CORE),
                'read_verilog -sv '+h.brace(h.PAIR)+' '+h.brace(ACC)+' '+h.brace(CORE))
            text=text.replace('SITES=12','SITES=20').replace('sites=12','sites=20')
            text=text.replace('$lut>90000','$lut>180000').replace('$ff>60000','$ff>100000')
            text=text.replace('[llength $dsps]>1152','[llength $dsps]!=1920').replace('$mult!=768','$mult!=1280').replace('$none>384','$none!=640')
            tcl.write_text(text)
            h.run('vivado_ooc',[h.VIVADO/'vivado.bat','-mode','batch','-source',tcl,
                '-log',out/'vivado.log','-journal',out/'vivado.jou'],build,out,d)
            dsp=[line.split('\t') for line in (out/'dsp48e1_sites12.tsv').read_text().splitlines()[1:]]
            modes=Counter(row[5] for row in dsp)
            require(modes==Counter(MULTIPLY=1280,NONE=640),'Exact20site DSP mode census')
            require(all(('packed_multiplier' in row[0]) if row[5]=='MULTIPLY' else
                        ('feedback_accumulator/feedback_adder' in row[0] and row[4]=='1') for row in dsp),'20site DSP ownership')
            util=(out/'utilization_sites12.rpt').read_text()
            lut=int(re.search(r'^\|\s*Slice LUTs\*?\s*\|\s*(\d+)',util,re.M)[1])
            ff=int(re.search(r'^\|\s*Slice Registers\s*\|\s*(\d+)',util,re.M)[1])
            bram=float(re.search(r'^\|\s*Block RAM Tile\s*\|\s*([\d.]+)',util,re.M)[1])
            require(lut<=180000 and ff<=100000 and bram==30,'20site Slice/BRAM resource screen')
            d.update(status='PASS_PRIVATE_20SITE_MAC_XSIM_OOC_ONLY',synthesis=dict(DSP=1920,
                DSP_modes=dict(modes),Slice_LUT=lut,FF=ff,BRAM36eq=bram,
                DCP_sha256=sha(build/'sites12_post_synth.dcp'),
                filename_note='Reused generator filenames say sites12; actualTcl generic andcensus areSITES20'),
                route_frequency_or_throughput_accepted=False)
    except Exception as exc:d.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    finally:
        d['source_sha256_after']={h.rel(p):sha(p) for p in paths}
        if before!=d['source_sha256_after']:d.update(status='FAILED_SOURCE_INTEGRITY',error='Source mutation')
        d['artifact_sha256']={h.rel(p):sha(p) for base in (out,build) for p in base.rglob('*') if p.is_file() and p!=report}
        report.write_text(json.dumps(d,indent=2)+'\n')
    print(json.dumps(dict(status=d['status'],report=str(report),error=d.get('error'))))
    return 0 if d['status'].startswith('PASS_') else 1


if __name__=='__main__':raise SystemExit(main())
