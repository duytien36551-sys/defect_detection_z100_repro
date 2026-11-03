#!/usr/bin/env python3
"""Run directed cancellation and recovery tests for guard V3 and the real parameter loader.

The AXI reader and config bridge remain protocol models; this is a helper/loader
control test, not a full backend quiet-fence or physical DDR test.
"""
from __future__ import annotations
import hashlib, json, re, subprocess
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HW=ROOT/'deployment/hardware/z100_2026'
HELPER=HW/'native_conv_backend_v3_resident_guard_v3/z100_parameter_residency_guard_v3.sv'
BACKEND=HW/'native_conv_backend_v3_resident_guard_v3/z100_native_conv_backend_v3_resident_guard_v3.sv'
MANIFEST=HW/'native_conv_backend_v3_resident_guard_v3/source_manifest_guard_v3.json'
LOADER=HW/'native_parameter_reader_v1/z100_native_parameter_reader.sv'
BASE_TB=HW/'guard_v3_loader_integration_test/tb_z100_guard_v3_parameter_loader_integration.sv'
TB=HW/'guard_v3_cancel_test/tb_z100_guard_v3_cancel_recovery.sv'
TOOLS=ROOT/'deployment/build/local_tools/iverilog13_msys2/ucrt64'
OUT=ROOT/'validation/board_z100/guard_v3_cancel'
BUILD=ROOT/'deployment/build/guard_v3_cancel'
EXPECTED={
 HELPER:'16f5a1d1a0da98ba8ba0c7842fd08eaaf26af97cdacc2b2570e730fb751e8aa1',
 BACKEND:'f8e57eeb8bb232e2323bdadaf9d161102bd4704bafb1cbe23c001374e53411e1',
 LOADER:'bf6779eded3740c57140526681f0f403964b6c54836076d469a25499bc1914a4',
}
PASS='Z100_GUARD_V3_CANCEL_RECOVERY_PASS'
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def rel(p:Path)->str:return p.resolve().relative_to(ROOT.resolve()).as_posix()
def run(name,argv,log):
 try:
  p=subprocess.run(argv,cwd=ROOT,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
  log.write_text(p.stdout,encoding='utf-8')
  return {'name':name,'argv':list(map(str,argv)),'return_code':p.returncode,'timed_out':False,'log':rel(log)}
 except subprocess.TimeoutExpired as e:
  val=e.stdout or ''
  if isinstance(val,bytes):val=val.decode('utf-8',errors='replace')
  log.write_text(val+'\nTIMEOUT after 180 seconds\n',encoding='utf-8')
  return {'name':name,'argv':list(map(str,argv)),'return_code':None,'timed_out':True,'log':rel(log)}
def main():
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
 evidence=OUT/stamp; build=BUILD/stamp
 evidence.mkdir(parents=True,exist_ok=False);build.mkdir(parents=True,exist_ok=False)
 report={'schema':'z100-guard-v3-cancel-recovery/1','status':'RUNNING','created_utc':datetime.now(timezone.utc).isoformat(),
  'scope':['actual guard-v3 helper RTL','actual native_parameter_reader RTL','directed cancellation in SEND, REPLY and COLLECT','repeat recover handshake then successful real-loader transaction'],
  'modeled':['AXI reader response source','configuration bridge ready/response peer','reader_quiet derived only from modeled reader_busy'],
  'limits':['not full backend dynamic simulation; no backend all_io_quiet proof','no physical DDR, numeric Conv, Vivado, board, full graph, or FPS evidence'],
  'board_access':False,'vivado_run':False,'commands':[],'issues':[]}
 try:
  compiler=TOOLS/'bin/iverilog.exe';vvp=TOOLS/'bin/vvp.exe';lib=TOOLS/'lib/ivl'
  for p in [compiler,vvp,lib,HELPER,BACKEND,MANIFEST,LOADER,BASE_TB,TB]:
   if not p.exists():raise FileNotFoundError(f'missing required input: {p}')
  hashes={rel(p):sha(p) for p in [HELPER,BACKEND,LOADER,BASE_TB,TB,MANIFEST]}
  for p,expected in EXPECTED.items():
   if hashes[rel(p)]!=expected:raise RuntimeError(f'pinned source drift: {rel(p)}')
  manifest=json.loads(MANIFEST.read_text(encoding='utf-8'))
  if manifest.get('sources',{}).get(rel(HELPER))!=hashes[rel(HELPER)] or manifest.get('sources',{}).get(rel(BACKEND))!=hashes[rel(BACKEND)]:
   raise RuntimeError('guard/backend hashes differ from stable candidate manifest')
  tb_text=TB.read_text(encoding='utf-8')
  for token in ["wait_for_loader_state(4'd1", "wait_for_loader_state(4'd2", "wait_for_loader_state(4'd4", 'recover_loader = 1', 'reader_command_count == 5']:
   if token not in tb_text:raise RuntimeError('coverage assertion missing: '+token)
  report.update(source_sha256=hashes,candidate_manifest=rel(MANIFEST),coverage_assertions=['SEND held with cfg_valid && !cfg_ready, then abort and recover','REPLY held after config acceptance with a deferred response, then abort and discard/recover','COLLECT held with reader_busy && reader_valid=0, then abort, explicitly drain, recover','post-recovery complete transaction reads all 4 parameter segments and publishes/retire completion','three recover handshakes return native loader from FAILED through CLEAR to IDLE'])
  binary=evidence/'guard_v3_cancel_recovery.vvp'
  cargv=[compiler,'-B',lib,'-g2012','-Wall','-s','tb_z100_guard_v3_cancel_recovery','-o',binary,HELPER,LOADER,TB]
  c=run('compile',cargv,evidence/'compile.log');report['commands'].append(c)
  if c['return_code']!=0 or not binary.is_file():raise RuntimeError('Icarus compile failed')
  sim=run('simulation',[vvp,binary],evidence/'simulation.log');report['commands'].append(sim)
  output=(evidence/'simulation.log').read_text(encoding='utf-8');report['simulation_output']=output.strip()
  if sim['return_code']!=0 or sim['timed_out'] or output.count(PASS)!=1 or re.search(r'FAIL|_FAIL',output):raise RuntimeError('directed cancellation/recovery assertions failed')
  report['status']='PASS_V3_CANCEL_RECOVERY_LOADER_HARNESS_ONLY'
 except Exception as e:
  report['status']='FAIL_CLOSED';report['issues']=[f'{type(e).__name__}: {e}']
 report['artifact_sha256']={rel(p):sha(p) for p in evidence.iterdir() if p.is_file()}
 result=evidence/'result.json';result.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'status':report['status'],'result':rel(result),'issues':report['issues']},indent=2))
 return 0 if report['status']=='PASS_V3_CANCEL_RECOVERY_LOADER_HARNESS_ONLY' else 1
if __name__=='__main__':raise SystemExit(main())
