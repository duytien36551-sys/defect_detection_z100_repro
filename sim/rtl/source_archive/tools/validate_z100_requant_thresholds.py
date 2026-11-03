"""Verify threshold boundaries against C for every fixture channel and simulate private RTL."""
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import random
import re
import struct
import subprocess
import uuid
import z100_requant_thresholds as rq
from validate_z100_reuse_sync import ROOT,sha256,VIVADO_DEFAULT,run_command


def probes(table):
    return sorted({rq.MINIMUM,rq.SENTINEL-1,-1,0,1}|{p+d for p in table for d in (-1,0,1) if rq.MINIMUM<=p+d<rq.SENTINEL})


def main():
    run=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    evidence=ROOT/'validation/board_z100/requant_threshold_v0'/run;evidence.mkdir(parents=True)
    build=ROOT/'deployment/build/z100_requant_threshold_v0'/run;build.mkdir(parents=True)
    hardware=ROOT/'deployment/hardware/z100_2026/requant_threshold_v0'
    package=ROOT/'deployment/candidates/pin640/validation/20261021_verified/pin/pipeline/package'
    sources=[package/'MODEL.V8P',package/'v8_generated_model.h',hardware/'oracle.c',hardware/'z100_requant_threshold.v',
             hardware/'tb_z100_requant_threshold.sv',ROOT/'tools/z100_requant_thresholds.py',Path(__file__).resolve()]
    identities={str(p.relative_to(ROOT)):sha256(p) for p in sources}
    (evidence/'launch.json').write_text(json.dumps(dict(run_id=run,source_sha256=identities),indent=2)+'\n')
    rows=rq.package_multipliers(package);vectors=0
    with (build/'boundaries.bin').open('wb') as stream,(build/'all_thresholds.bin').open('wb') as output:
        for row in rows:
            multiplier=row['multiplier'];table=rq.thresholds(multiplier)
            output.write(struct.pack('<254q',*table))
            for raw in probes(table):
                result=rq.evaluate(raw,table)
                if result!=rq.oracle(raw,multiplier):raise ValueError('Python boundary mismatch')
                stream.write(struct.pack('<dib',multiplier,raw,result));vectors+=1
    gcc=Path('C:/cbian/mingw64/bin/gcc.exe');executable=build/'oracle.exe'
    compiled=subprocess.run([str(gcc),'-std=c11','-O2','-Wall','-Wextra','-Werror','-fno-fast-math','-ffp-contract=off',
                             str(hardware/'oracle.c'),'-lm','-o',str(executable)],capture_output=True,text=True)
    (evidence/'gcc.log').write_text(compiled.stdout+'\n'+compiled.stderr)
    if compiled.returncode:raise ValueError('C oracle compilation failed')
    checked=subprocess.run([str(executable),str(build/'boundaries.bin')],capture_output=True,text=True)
    (evidence/'c_oracle.log').write_text(checked.stdout+'\n'+checked.stderr)
    if checked.returncode or f'C_ORACLE_PASS vectors={vectors}' not in checked.stdout:raise ValueError('C oracle failed')
    selected=[rows[0]['multiplier'],rows[len(rows)//2]['multiplier'],rows[-1]['multiplier'],
              2.0**-40,.5,1.0,2.0,math.nextafter(.5,1.0)]
    tables=[];inputs=[];expected=[];randomizer=random.Random(640)
    for multiplier in selected:
        table=rq.thresholds(multiplier);tables.extend(table)
        samples=probes(table)
        while len(samples)<1024:samples.append(randomizer.randint(rq.MINIMUM,rq.SENTINEL-1))
        if len(samples)>1024:raise ValueError('Probe bound changed')
        inputs.extend(samples);expected.extend(rq.oracle(raw,multiplier) for raw in samples)
    for name,values,bits,width in [('tables',tables,33,9),('inputs',inputs,32,8),('expected',expected,8,2)]:
        (build/(name+'.hex')).write_text(''.join(f'{v&((1<<bits)-1):0{width}x}\n' for v in values))
    bindir=VIVADO_DEFAULT.parent
    commands=[('xvlog',[str(bindir/'xvlog.bat'),'-sv',str(hardware/'z100_requant_threshold.v'),str(hardware/'tb_z100_requant_threshold.sv')]),
              ('xelab',[str(bindir/'xelab.bat'),'-mt','2','tb_z100_requant_threshold','-s','requant_sim']),
              ('xsim',[str(bindir/'xsim.bat'),'requant_sim','-runall'])]
    phases=[];coverage=None
    for name,command in commands:
        result=run_command(command,build,evidence/(name+'.log'));phases.append({k:v for k,v in result.items() if k!='output'})
        if result['return_code']!=0:raise ValueError(name+' failed')
        if name=='xsim':
            text=result['output']
            matches=re.findall(r'REQUANT_PASS cases=(\d+) cancels=16 errors=1 reset=1 max_search_cycles=16',text)
            if 'Fatal:' in text or 'FAIL' in text or matches!=['8193']:raise ValueError('Requant RTL simulation failed')
            coverage=dict(cases=8193,cancels=16,errors=1,resets=1,max_search_cycles=16)
    if identities!={str(p.relative_to(ROOT)):sha256(p) for p in sources}:raise ValueError('Sources changed')
    report=dict(status='PASS_PRIVATE_EXACT_REQUANT_THRESHOLDS',source_sha256=identities,commands=phases,
                convolution_nodes=63,channels=len(rows),c_boundary_vectors=vectors,rtl=coverage,
                thresholds_per_channel=254,threshold_bits=33,all_table_compact_bytes=len(rows)*254*5,
                private32lane_capacity_bits=32*254*33,selected_multipliers=selected,
                artifacts_sha256={str(p.relative_to(ROOT)):sha256(p) for p in [*build.glob('*.hex'),build/'boundaries.bin',build/'all_thresholds.bin',*evidence.glob('*.log')]},
                physical_board_tested=False,production_integrated=False,final_model_accepted=False,release_eligible=False,
                proof_scope='Positive finite binary64 multiplier monotonicity; exact integer transition search plus C boundary/neighbor checks, not2^32 enumeration',
                throughput_scope='One serialized lane, up to16 search clocks; not a32lane pipelined throughput implementation')
    (evidence/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],channels=len(rows),vectors=vectors,report=str(evidence/'result.json'))))


if __name__=='__main__':main()
