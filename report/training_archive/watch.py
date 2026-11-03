"""Read-only terminal viewer; Ctrl+C closes the view, not training."""
from pathlib import Path
import json
import time
from datetime import datetime
HERE=Path(__file__).resolve().parent
last=None
try:
    while True:
        status=json.loads((HERE/'status.json').read_text(encoding='utf-8'))
        path=HERE/'runs/pin/progress.json'
        progress=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if progress!=last:
            print(f'[{datetime.now():%m-%d %H:%M:%S}] {status["state"]} {progress.get("state", "")}',flush=True)
            if 'batch' in progress:
                print(f'Epoch {progress["epoch"]}/{progress["epochs"]} batch {progress["batch"]}/{progress["batches"]} ({100*progress["batch"]/progress["batches"]:.1f}%)',flush=True)
            elif 'validation' in progress:
                metrics=progress['validation']
                print(f'Epoch {progress["epoch"]} AP50={100*metrics["ap50"]:.2f}% AP50:95={100*metrics["ap50_95"]:.2f}%',flush=True)
            last=progress
        if status['state'] in ['completed','needs_attention']:
            print(status,flush=True)
            break
        time.sleep(5)
except KeyboardInterrupt:
    print('Viewer closed; training continues.',flush=True)
