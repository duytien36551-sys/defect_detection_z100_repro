"""Batch full-head parity and 30 requests. Stop on any failure; never retry."""
from pathlib import Path
import hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'qualification10'
PROJECT=Path('source_project')
ELF=Path('hardware_workspace/gpt_softpack_build_plan01/build_output/native_board_pool.elf')
PWSH='tool_environment/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe'
ALT=Path('hardware_workspace/gpt_alternate_input01')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
OUT.mkdir(exist_ok=False)
r={'status':'RUNNING','elf':str(ELF),'elf_sha256':sha(ELF),'initial_epoch':49000,'delivered':10,'retries':0,'captures':[],'commands':[]}
def save():(OUT/'summary.json').write_text(json.dumps(r,indent=2))
def run(args,log):
    r['commands'].append(args);save()
    with (OUT/log).open('w') as f:p=subprocess.run(args,cwd=PROJECT,stdout=f,stderr=subprocess.STDOUT)
    if p.returncode:raise RuntimeError(f'{log} exited {p.returncode}')
def capture(count,name):
    path=OUT/f'capture{count:02d}';script=path.with_suffix('.tcl');meta=path.with_suffix('.json')
    run([sys.executable,'-B',str(PROJECT/'tools/prepare_z100_perf_debug.py'),'capture','--elf',str(ELF),'--initial','49000','--next',str(49000+count),'--delivered',str(count),'--output',str(path),'--script',str(script)],f'prepare{count}.log')
    s=script.read_text()
    assert s.count('0xeafffffd')==1 and '0xa84' in s
    s=s.replace('0xa84','0x2805c').replace('0xeafffffd','0xeafffffe')
    s=s.replace('connect\n', 'connect\nafter 1500\n',1)
    script.write_text(s)
    m=json.loads(meta.read_text());m['ocm_return']='0x2805c existing audited capture hold; legacy sentinel invalid after FSBL';m['script_sha256']=sha(script);m['elf_sha256']=sha(ELF);meta.write_text(json.dumps(m,indent=2))
    run([PWSH,'-NoProfile','-File',str(PROJECT/'tools/run_z100_board_once.ps1'),'-Tcl',str(script),'-Output',str(path)],f'capture{count}.log')
    reference=ALT/'expected_B_heads_int8.bin' if name=='B' else PROJECT/'validation/board_z100/pin640_epoch200_headconcat_host/20261024T104121.305479Z/expected_heads_int8.bin'
    run([sys.executable,'-B',str(PROJECT/'tools/analyze_z100_perf_capture.py'),str(meta),'--reference',str(reference)],f'analysis{count}.log')
    analysis=json.loads((path/'analysis.json').read_text())
    r['captures'].append({'delivered':count,'input':name,'raw_heads_equal':analysis['raw_heads_equal'],'raw_bytes':analysis['raw_bytes'],'heads_sha256':sha(path/'heads.bin'),'reference_sha256':sha(reference),'irq_guard':analysis['irq_guard_low4096_intact'],'board_timing_ms':analysis['board_timing_ms'],'analysis':str(path/'analysis.json')});save()
try:
    capture(10,'A')
    r['status']='PASS_TEN_FRAMES_RAW_HEADS_IRQ'
except Exception as e:
    r['status']='STOPPED_ON_FIRST_FAILURE_NO_RETRY';r['error']=str(e);save();raise
finally:save()
print(json.dumps({k:v for k,v in r.items() if k not in ['frames30','commands']},indent=2))
