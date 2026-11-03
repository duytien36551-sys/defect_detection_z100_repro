"""Miter simulation-only arithmetic refs against original vendor DSP test suites."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,os,re,subprocess
ROOT=Path(__file__).resolve().parents[1];HW=ROOT/'deployment/hardware/z100_2026';VENDOR=Path('C:/appload/2026.1/Vivado/bin')
REFERENCE=ROOT/'deployment/simulation/native_primitive_ref/z100_native_primitive_ref.sv'
PROOFS=[ROOT/'validation/board_z100/int8_pair_packing_v3/20261024T044617.750422Z/result.json',ROOT/'validation/board_z100/accum33_dsp_v2/20261024T051501.085372Z/result.json']
PAIR=r'''
wire fast_valid;wire signed[15:0] fast_low,fast_high;integer fast_checks=0;
z100_int8_pair_packing_fast_ref reference_unit(.clk(clk),.rst_n(rst_n),.cancel(cancel),.in_valid(in_valid),
 .in_activation(in_activation),.in_weight_low(in_weight_low),.in_weight_high(in_weight_high),.out_valid(fast_valid),.out_product_low(fast_low),.out_product_high(fast_high));
always @(posedge clk)begin
 #2;if(fast_valid!==out_valid)$fatal(1,"Fast pair validity differs from actual DSP");
 if(out_valid)begin if({fast_low,fast_high}!=={out_product_low,out_product_high})$fatal(1,"Fast pair differs from actual DSP");fast_checks=fast_checks+1;end
end
'''
ACCUM=r'''
wire fast_valid,fast_overflow;wire signed[32:0] fast_value;wire signed[31:0] fast_clamped;integer fast_checks=0;
z100_accum33_dsp_fast_ref reference_unit(.clk(clk),.rst_n(rst_n),.cancel(cancel),.load_bias(load_bias),.enable(enable),.bias(bias),.delta(delta),
 .value_valid(fast_valid),.value(fast_value),.clamped(fast_clamped),.overflow(fast_overflow));
always @(posedge clk)begin
 #2;if({fast_valid,fast_value,fast_clamped,fast_overflow}!=={value_valid,value,clamped,overflow})$fatal(1,"Fast accumulator differs from actual DSP");fast_checks=fast_checks+1;
end
'''
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def resolve(n):
    p=Path(n);return Path(p.parts[1]+':/',*p.parts[2:]) if p.parts[0]=='external' else ROOT/p
def require(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prepare-only',action='store_true');a=ap.parse_args()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out=ROOT/'validation/board_z100/native_primitive_refs'/stamp;build=ROOT/'build'/('nprf_'+stamp[-14:]);out.mkdir(parents=True);build.mkdir(parents=True)
    report=out/'result.json';before={};r=dict(status='RUNNING',commands=[],board_access=False,full_pipeline_30fps_accepted=False,simulation_references_only=True)
    try:
        for p in PROOFS:
            q=json.loads(p.read_text());require(q['status'].startswith('PASS_'),'Actual DSP prerequisite')
            require(q['source_sha256_before']==q['source_sha256_after'],'Stable actual DSP proof')
            for n,h in {**q['source_sha256_after'],**q['artifact_sha256']}.items():require(sha(resolve(n))==h,'DSP prerequisite artifact '+n)
        pair_proof=json.loads(PROOFS[0].read_text());require(pair_proof['host']['triples']==16777216 and pair_proof['simulation']['consecutive_ii1']==1048576,'Full signed pair host proof and original million-cycle vendor suite')
        specs=[('pair',HW/'int8_pair_packing_v3/z100_int8_pair_packing.sv',HW/'int8_pair_packing_v3/tb_z100_int8_pair_packing.sv','tb_z100_int8_pair_packing',PAIR,1048576),('accum',HW/'accum33_dsp_v2/z100_accum33_dsp.sv',HW/'accum33_dsp_v2/tb_z100_accum33_dsp.sv','tb_z100_accum33_dsp',ACCUM,16700)]
        generated=[]
        for name,module,tb,top,body,minimum in specs:
            text=tb.read_text();require(text.count('endmodule')==1 and text.count('$finish;')==1,'Single original miter seam')
            text=text.replace(top,top+'_fast_miter').replace('endmodule',body+'\nendmodule')
            text=text.replace('$finish;',f'if(fast_checks<{minimum})$fatal(1,"Fast reference miter coverage");$display("FAST_REFERENCE_MITER_PASS kind={name} checks=%0d",fast_checks);$finish;')
            target=build/(top+'_fast_miter.sv');target.write_text(text);generated.append((name,module,tb,top+'_fast_miter',target))
        glbl=VENDOR.parent/'data/verilog/src/glbl.v';sources=[Path(__file__),REFERENCE,*PROOFS,glbl,*[p for spec in generated for p in spec[1:3]],*[spec[4] for spec in generated]]
        before={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else 'external/'+p.as_posix().replace(':',''):sha(p) for p in sources};r['source_sha256_before']=before
        r['scope']='Original signed-pair exhaustive-host proof and million-cycle actual MULT_MACRO suite retained; original signed33 DSP48E1 enable/load/reset/cancel/saturation suite retained. Added edge-by-edge comparison against simulation-only behavioral references. No complete arithmetic replacement is authorized until this miter passes, and no behavioral simulation proves mapped resources, routed timing or physical FPS. Production modules/source lists unchanged.'
        report.write_text(json.dumps(r,indent=2)+'\n')
        if a.prepare_only:r['status']='PREPARED_SIMULATION_ONLY_PRIMITIVE_MITERS_NOT_EXECUTED'
        else:
            def run(label,argv):
                p=subprocess.run(list(map(str,argv)),cwd=build,env=dict(os.environ,XILINX_LOCAL_USER_DATA='no'),text=True,encoding='utf-8',errors='replace',capture_output=True);logs=p.stdout+'\n'+p.stderr;(out/(label+'.log')).write_text(logs);r['commands'].append(dict(args=list(map(str,argv)),return_code=p.returncode));require(p.returncode==0 and not re.search(r'^\s*(ERROR:|Fatal:)',logs,re.M),'Actual '+label);return logs
            run('xvlog',[VENDOR/'xvlog.bat','-sv',REFERENCE,glbl,*[spec[1] for spec in generated],*[spec[4] for spec in generated]])
            r['miters']=[]
            for name,module,tb,top,target in generated:
                run(name+'_xelab',[VENDOR/'xelab.bat','-mt','2','-L','unimacro_ver','-L','unisims_ver',top,'glbl','-s',name+'_miter'])
                logs=run(name+'_xsim',[VENDOR/'xsim.bat',name+'_miter','-runall']);markers=re.findall('^FAST_REFERENCE_MITER_PASS kind='+name+r' checks=(\d+)$',logs,re.M);require(len(markers)==1,'Complete actual '+name+' miter marker');r['miters'].append(dict(kind=name,checks=int(markers[0])))
            r['status']='PASS_SIMULATION_REFERENCES_MATCH_ACTUAL_VENDOR_PAIR_AND_ACCUM_SUITES_NOT_PLATFORM'
    except Exception as e:r.update(status='FAILED_CLOSED',error=f'{type(e).__name__}: {e}')
    r['source_sha256_before']=before;r['source_sha256_after']={n:sha(resolve(n)) for n in before}
    if before!=r['source_sha256_after']:r['status']='FAILED_SOURCE_INTEGRITY'
    r['artifact_sha256']={str(p.relative_to(ROOT)):sha(p) for folder in (out,build) for p in folder.rglob('*') if p.is_file() and p!=report}
    report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(status=r['status'],report=str(report),error=r.get('error'))));return int(r['status'].startswith('FAILED'))
if __name__=='__main__':raise SystemExit(main())
