from pathlib import Path
import json,subprocess,sys
ROOT=Path(__file__).resolve().parent;PROJECT=Path('source_project')
PWSH='tool_environment/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe'
report=ROOT/'batch_result.json'
if report.exists():raise RuntimeError('No repeated batch')
r={'status':'STARTED','retries':0}
def save():report.write_text(json.dumps(r,indent=2))
def board(tcl,out):return subprocess.run([PWSH,'-NoProfile','-File',str(PROJECT/'tools/run_z100_board_once.ps1'),'-Tcl',str(ROOT/tcl),'-Output',str(ROOT/out)],cwd=PROJECT).returncode
gate=json.loads((ROOT/'suite_preflight.json').read_text());assert gate['status']=='PASS_13_MOCKS'
assert gate['launch_sha256']==__import__('hashlib').sha256((ROOT/'launch.tcl').read_bytes()).hexdigest()
assert json.loads((ROOT/'primary_review.json').read_text())['status']=='PASS_PRIMARY_BUILD_LAUNCH_REVIEW'
save();r['launch_returncode']=board('launch.tcl','board_once01');save()
if r['launch_returncode']:r['status']='LAUNCH_FAILED_NO_REQUESTS';save();sys.exit(1)
r['frames_returncode']=subprocess.run([sys.executable,'-B',str(PROJECT/'tools/run_z100_perf_batch.py'),'--output',str(ROOT/'frames10'),'--count','10'],cwd=PROJECT).returncode;save()
if r['frames_returncode']:
    r['capture_returncode']=board('capture_failure.tcl','failure_capture01');r['status']='FIRST_FAILURE_STOPPED_NO_RETRY';save();sys.exit(1)
r['status']='TEN_RESULTS_PASS_FULL_HEADS_PENDING';save();print(json.dumps(r,indent=2))
