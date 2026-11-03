"""Single-domain durable training supervisor, no dependency on AI availability."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
from datetime import datetime

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT))
import torch
import psutil
from train_experiment import write_json
torch.set_num_threads(1)


def status(state,**fields):
    write_json(HERE/'status.json',dict(state=state,supervisor_pid=os.getpid(),updated_at=datetime.now().astimezone().isoformat(),**fields))


def launch(stage,extra):
    assert not (HERE/'stop').exists(),'User stop marker; refusing restart'
    plan=json.loads((HERE/'plan.json').read_text(encoding='utf-8'))
    with (HERE/f'{stage}_stdout.log').open('ab') as out,(HERE/f'{stage}_stderr.log').open('ab') as err:
        child=subprocess.Popen([plan['python'],'-u',str(HERE/'run.py'),'--domain','pin',*extra],
                               cwd=ROOT,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW,
                               env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1'))
        status('running',stage=stage,launcher_pid=child.pid)
        return child.wait()


def main():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.restype=ctypes.c_void_p
    handle=kernel.CreateMutexW(None,False,'Local\\V8PinPaperStyle300Epoch20261021')
    if not handle or ctypes.get_last_error()==183:return
    for p in psutil.process_iter(['pid','cmdline']):
        if str(HERE/'run.py').lower() in [s.lower() for s in p.info['cmdline'] or []]:
            status('needs_attention',reason='Existing worker; duplicate rejected');return
    try:
        plan=json.loads((HERE/'plan.json').read_text(encoding='utf-8'))
        assert json.loads((HERE/'preflight.json').read_text(encoding='utf-8'))['status']=='passed'
        run=HERE/'runs/pin'
        checkpoint=run/'weights/resume.pt'
        for attempt in range(3):
            if (run/'completion.json').exists():break
            extra=[]
            if checkpoint.exists():
                ck=torch.load(checkpoint,map_location='cpu',weights_only=False)
                assert all(ck.get(k) is not None for k in ['optimizer','scheduler','live_state','ema'])
                assert ck['optimizer']['state']
                if ck['epoch']==plan['epochs_per_model']-1:
                    records=[json.loads(p.read_text(encoding='utf-8')) for p in sorted(run.glob('epoch_*.json'))]
                    assert [r['epoch'] for r in records]==list(range(1,plan['epochs_per_model']+1))
                    best=max(records,key=lambda r:r['validation']['ap50_95'])
                    write_json(run/'completion.json',dict(completed_epochs=plan['epochs_per_model'],best_epoch=best['epoch'],seconds=sum(r['seconds'] for r in records)))
                    break
                extra=['--resume',str(checkpoint)]
            code=launch('training',extra)
            if code and not checkpoint.exists():raise RuntimeError('Training failed before first durable checkpoint')
        assert (run/'completion.json').exists(),'Training retry limit reached'
        if not (HERE/'evaluation/pin/best/metrics.json').exists():
            assert launch('evaluation',['--evaluate','best'])==0,'Best validation failed'
        completion=json.loads((run/'completion.json').read_text(encoding='utf-8'))
        metrics=json.loads((HERE/'evaluation/pin/best/metrics.json').read_text(encoding='utf-8'))
        write_json(HERE/'final_report.json',dict(completion=completion,validation=metrics,
                   protocol='New source-group8:1:1 split; no fair direct old-split comparison; test not evaluated',
                   test_used=False,initialization='random',paper_exact_reproduction=False))
        status('completed',report=str(HERE/'final_report.json'))
    except Exception as exc:
        traceback.print_exc()
        status('needs_attention',reason=f'{type(exc).__name__}: {exc}')


if __name__=='__main__':main()
