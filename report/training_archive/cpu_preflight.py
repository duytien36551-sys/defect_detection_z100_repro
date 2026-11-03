"""Resource-bounded batch32/640 check, no dataset or production weight changes."""
from pathlib import Path
import os
import sys
import json
import time
import subprocess
import traceback
ROOT=Path(__file__).resolve().parent
BATCH=int(sys.argv[sys.argv.index('--batch')+1]) if '--batch' in sys.argv else 32

if '--child' in sys.argv:
    result={}
    try:
        import torch
        from ultralytics.nn.tasks import DetectionModel
        from ultralytics.cfg import get_cfg
        torch.set_num_threads(6)
        torch.manual_seed(20261021)
        model=DetectionModel(str(ROOT/'yolov8n_scratch9.yaml'),ch=3,nc=9,verbose=False).train()
        model.args=get_cfg()
        optimizer=torch.optim.SGD(model.parameters(),lr=.01,momentum=.937)
        batch={'img':torch.rand(BATCH,3,640,640),'batch_idx':torch.arange(BATCH).float(),
               'cls':torch.zeros(BATCH,1),'bboxes':torch.tensor([[.5,.5,.2,.2]]*BATCH)}
        started=time.perf_counter()
        loss,_=model(batch)
        loss=loss.sum()
        loss.backward()
        optimizer.step()
        result=dict(status='passed',device='cpu',batch=BATCH,imgsz=640,loss=loss.item(),seconds=time.perf_counter()-started,
                    finite_gradients=all(torch.isfinite(p.grad).all().item() for p in model.parameters() if p.grad is not None))
        assert result['finite_gradients']
    except Exception:
        result=dict(status='failed',traceback=traceback.format_exc())
    (ROOT/f'cpu_preflight_batch{BATCH}_result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)
else:
    import psutil
    env=dict(os.environ,YOLO_CONFIG_DIR=str(ROOT.parent/'.ultralytics'),PYTHONIOENCODING='utf-8')
    with (ROOT/'cpu_preflight.log').open('w',encoding='utf-8') as log:
        child=subprocess.Popen([sys.executable,'-u',__file__,'--child','--batch',str(BATCH)],stdout=log,stderr=log,cwd=ROOT,env=env)
        proc=psutil.Process(child.pid)
        started=time.monotonic();peak=0;minimum=psutil.virtual_memory().available;reason=None
        while child.poll() is None:
            tree=[proc]+proc.children(recursive=True)
            rss=sum(p.memory_info().rss for p in tree if p.is_running())
            peak=max(peak,rss);minimum=min(minimum,psutil.virtual_memory().available)
            if minimum<1024**3 or rss>6*1024**3 or time.monotonic()-started>90:
                reason='memory_or_timeout_guard'
                for p in reversed(tree):
                    if p.is_running():p.kill()
                break
            time.sleep(.2)
        child.wait()
        summary=dict(exit_code=child.returncode,peak_python_tree_rss_gib=peak/1024**3,min_free_gib=minimum/1024**3,guard_reason=reason)
        (ROOT/f'cpu_preflight_batch{BATCH}_resources.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(json.dumps(summary),flush=True)
