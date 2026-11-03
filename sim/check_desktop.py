"""Check the packaged desktop UI without network or board access."""
from pathlib import Path
import sys
import json
import tkinter as tk
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from board.run_desktop import configuration
from src.desktop import app as ui
from src.desktop.preprocess import prepare_image

model,names=configuration()
root=tk.Tk()
root.withdraw()
errors=[]
root.report_callback_exception=lambda *error:errors.append(repr(error))
app=ui.App(root,host='127.0.0.1',port=1,model=model,names=names,allow_host_reference=False,timeout=1)
app.playback_delay.set(0)
calls=[]
class FakeClient:
    def infer(self,tensor,mapping,task):
        assert len(tensor)==1228800 and task=='all'
        calls.append(task)
        return [{'class_id':0,'class_name':names[0],'score':0.9,'xyxy':[30,30,90,90]}]
app._client=lambda timeout:FakeClient()
try:
    with tempfile.TemporaryDirectory() as tmp:
        from PIL import Image
        path=Path(tmp)/'sample.png'
        Image.new('RGB',(320,240),(100,100,100)).save(path)
        ui.HISTORY_DIR=Path(tmp)/'history'
        app._import_paths([path])
        app.start_batch()
        deadline=time.perf_counter()+8
        while app.busy and time.perf_counter()<deadline:
            root.update();time.sleep(.01)
        assert not app.busy and not errors
        assert calls==['all']
        assert not hasattr(app,'resource_metrics')
        assert len(list(ui.HISTORY_DIR.glob('*.json')))==1
        assert app.records[str(path.resolve())]['status']=='已完成'
    print(json.dumps(dict(status='PASS_PACKAGED_DESKTOP_UI',network_used=False,board_access=False,
                         inference='explicit_fake_for_ui_test',tk_callback_errors=errors),indent=2))
finally:
    app._close()
