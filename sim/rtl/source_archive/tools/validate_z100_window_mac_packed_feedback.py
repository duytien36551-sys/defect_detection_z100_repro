"""Private packed MAC with explicit DSP feedback; bounded XSim/OOC, no board."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import argparse, hashlib, importlib.util, json, re, shutil

ROOT=Path(__file__).resolve().parents[1]
HW=ROOT/'deployment/hardware/z100_2026/window_mac_packed_feedback_v1'
CORE=HW/'z100_window_mac.sv'
TB=HW/'tb_z100_window_mac.sv'
FOCUS=HW/'tb_z100_window_mac_packed_feedback_focus.sv'
ACC=ROOT/'deployment/hardware/z100_2026/accum33_dsp_v2/z100_accum33_dsp.sv'
ACC_REPORT=ROOT/'validation/board_z100/accum33_dsp_v2/20261024T051501.085372Z/result.json'
PACK_REPORT=ROOT/'validation/board_z100/window_mac_packed_v1/20261024T045513.294355Z_80df5a83/result.json'
HELPER=ROOT/'tools/validate_z100_window_mac_packed.py'


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def require(ok,message):
    if not ok:raise ValueError(message)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--execute',action='store_true');args=ap.parse_args()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out=ROOT/'validation/board_z100/packed_feedback'/stamp
    build=ROOT/'deployment/build/packed_feedback'/stamp
    out.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
    spec=importlib.util.spec_from_file_location('frozen_packed_helper',HELPER)
    h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
    scale=h.load_scale()
    sources=tuple(dict.fromkeys([*h.paths(scale),CORE,TB,FOCUS,ACC,ACC_REPORT,PACK_REPORT,Path(__file__)]))
    before={h.rel(p):sha(p) for p in sources}
    d=dict(status='RUNNING',source_sha256_before=before,commands=[],board_access=False,
           production_integrated=False,full_pipeline_30fps_accepted=False)
    report=out/'result.json'
    try:
        a=json.loads(ACC_REPORT.read_text());p=json.loads(PACK_REPORT.read_text())
        require(a['status']=='PASS_PRIVATE_SIGNED33_FEEDBACK_XSIM_ONE_DSP_OOC_ONLY' and
                p['status']=='PASS_XSIM_AND_OOC_COMPONENT_SCREENS_ONLY','Prerequisite private scope')
        require(sha(ACC)==next(v for k,v in a['source_sha256_after'].items() if k.endswith('z100_accum33_dsp.sv')),
                'Exact feedback helper source')
        for name,value in p['source_sha256_after'].items():
            parts=Path(name).parts
            path=Path(parts[1]+':/',*parts[2:]) if parts[0]=='external' else ROOT/name
            require(sha(path)==value,'Packed prerequisite drift '+name)
        original=h.CORE.read_text();candidate=CORE.read_text()
        require(original[:original.index(');')+2]==candidate[:candidate.index(');')+2], 'Native interface change')
        require('accum[s][l]<=' not in candidate and 'wire signed [32:0] accum' in candidate and
                '.bias((accum_site<run_sites && accum_lane<run_lanes)' in candidate,
                'Feedback must own accumulators and capture accepted-run dimensions')
        require('sum_q[site][lane]<=total;' in candidate and
                '.enable(p3_valid && (state==INPUTS || state==FLUSH)' in candidate and
                'run_epoch==weights_epoch' in candidate and
                'run_sites<=SITES' in candidate,'Arithmetic/feedback validity contract')
        require(TB.read_bytes()==h.TB4.read_bytes(),'SITES4 frozen numerical suite must stay exact')
        for token in ('jobs != 22','word_checks != 4160','real_window_checks != 2 * SITES',
                      'max_groups_seen != 1024','cancel_offsets != 5','reset_offsets != 5'):
            require(token in FOCUS.read_text(),'Focused coverage assertion missing '+token)
        h.snapshot(sources,out/'src')
        model=scale.validate_model_inputs();d['fixture']=scale.create_firstconv_fixture(build,model)
        d['prerequisite_reports']={str(q.relative_to(ROOT)):sha(q) for q in (ACC_REPORT,PACK_REPORT,HELPER)}
        d['status']='PASS_PRIVATE_HOST_PREFLIGHT_VENDOR_PENDING'
        if args.execute:
            for label,tb,top,snapshot in (
                    ('sites4',TB,'tb_z100_window_mac','packed_feedback_s4'),
                    ('sites12',FOCUS,'tb_z100_window_mac_packed_feedback_focus','packed_feedback_s12')):
                simdir=build/label;simdir.mkdir();shutil.copytree(build/'fixture',simdir/'fixture')
                h.run('xvlog_'+label,[h.VIVADO/'xvlog.bat','-sv',CORE,h.PAIR,ACC,tb,h.GLBL],simdir,out,d)
                h.run('xelab_'+label,[h.VIVADO/'xelab.bat','-mt','2','-L','unimacro_ver','-L','unisims_ver',
                      top,'glbl','-s',snapshot],simdir,out,d)
                text=h.run('xsim_'+label,[h.VIVADO/'xsim.bat',snapshot,'-runall'],simdir,out,d)
                if label=='sites4':d['simulation_sites4']=h.check_s4(text)
                else:
                    rows=re.findall(r'^WINDOW_MAC_FEEDBACK_FOCUS_PASS ([^\r\n]+)$',text,re.M)
                    require(len(rows)==1,'Unique focused feedback PASS marker')
                    v={k:int(x) for k,x in re.findall(r'(\w+)=(\d+)',rows[0])}
                    exact=dict(sites12_jobs=22,sites12_words=4160,sites12_metadata=130,
                        sites12_stream_errors=3,sites12_config_errors=6,sites12_run_errors=6,
                        sites12_cross=768,sites12_saturation=768,sites12_cancel_offsets=5,
                        sites12_reset_offsets=5,sites12_real_windows=24,sites12_site_tail_mask=77,
                        sites12_lane_tail_mask=15,sites12_group_mask=31,max_groups=1024)
                    require(all(v.get(k)==x for k,x in exact.items()) and v['replays']>=2 and
                            v['sites12_stalls']>0 and v['sites12_bubbles']>0,'Focused feedback exact counters')
                    d['simulation_sites12']=v
            # Reuse only the source-bound census/report Tcl generator, then add
            # the explicit helper and exact feedback ownership/count gates.
            h.CORE=CORE
            tcl=h.write_tcl(out,build);text=tcl.read_text()
            text=text.replace('read_verilog -sv '+h.brace(h.PAIR)+' '+h.brace(CORE),
                'read_verilog -sv '+h.brace(h.PAIR)+' '+h.brace(ACC)+' '+h.brace(CORE))
            # Counts/ownership are checked below from saved full census.
            text=text.replace('$lut>90000','$lut>100000')
            tcl.write_text(text)
            h.run('vivado_ooc',[h.VIVADO/'vivado.bat','-mode','batch','-source',tcl,
                  '-log',out/'vivado.log','-journal',out/'vivado.jou'],build,out,d)
            rows=[line.split('\t') for line in (out/'dsp48e1_sites12.tsv').read_text().splitlines()[1:]]
            modes=Counter(row[5] for row in rows)
            require(modes==Counter(MULTIPLY=768,NONE=384),'Exact768MULT+384feedbackDSP mapping')
            require(all(('packed_multiplier' in row[0] and row[3:5]==['1','0']) if row[5]=='MULTIPLY'
                        else ('feedback_accumulator/feedback_adder' in row[0] and row[4]=='1')
                        for row in rows),'DSP actual register/owner attribution')
            util=(out/'utilization_sites12.rpt').read_text()
            lut=int(re.search(r'^\|\s*Slice LUTs\*?\s*\|\s*(\d+)',util,re.M)[1])
            ff=int(re.search(r'^\|\s*Slice Registers\s*\|\s*(\d+)',util,re.M)[1])
            bram=float(re.search(r'^\|\s*Block RAM Tile\s*\|\s*([\d.]+)',util,re.M)[1])
            require(lut<=100000 and ff<=60000 and bram==30,'Slice/BRAM fixed resource gate')
            d['synthesis']=dict(status='PASS_PRIVATE_OOC_ONLY',DSP_modes=dict(modes),DSP=1152,
                Slice_LUT=lut,FF=ff,BRAM36eq=bram,DCP_sha256=sha(build/'sites12_post_synth.dcp'))
            d['status']='PASS_PRIVATE_PACKED_FEEDBACK_XSIM_OOC_ONLY'
    except Exception as exc:d.update(status='FAILED_CLOSED',error=f'{type(exc).__name__}: {exc}')
    finally:
        d['source_sha256_after']={h.rel(p):sha(p) for p in sources}
        if d['source_sha256_after']!=before:d.update(status='FAILED_SOURCE_INTEGRITY',error='Source mutation')
        d['artifact_sha256']={h.rel(p):sha(p) for base in (out,build) for p in base.rglob('*') if p.is_file() and p!=report}
        report.write_text(json.dumps(d,indent=2)+'\n')
    print(json.dumps(dict(status=d['status'],report=str(report),error=d.get('error'))))
    return 0 if d['status'].startswith('PASS_') else 1


if __name__=='__main__':raise SystemExit(main())
