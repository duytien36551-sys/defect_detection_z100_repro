"""Compare desktop pixels and Python/C raw-head decode with actual official YOLOv8."""
import json
import os
from pathlib import Path
import sys
import ctypes
import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1]
os.environ['YOLO_CONFIG_DIR']=str(ROOT/'.config')
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'reference')]
from decode_parity import DecodeParity
from desktop.preprocess import prepare_bgr,load_bgr
from v8_decode import decode_raw_heads
from ultralytics import YOLO
from ultralytics.data.augment import LetterBox
from ultralytics.utils.nms import non_max_suppression


def main():
    torch.set_num_threads(1)
    out=ROOT/'validation/stage2';out.mkdir(parents=True,exist_ok=True)
    model=YOLO(str(ROOT/'model/stage28/source.pt')).model.float().eval()
    manifest=ROOT.parent/'resources/training_source/data/trainval_dataset.json'
    data=json.loads(manifest.read_text(encoding='utf-8'))
    rows=[]
    for prefix in ('pcb_','pin_'):
        rows.extend([r for r in data['records'] if r['split']=='val' and r['id'].startswith(prefix)][:8])
    prep=[]
    rng=np.random.default_rng(23)
    for h,w in [(237,239),(226,226),(320,640),(641,319),(416,416),(1,416)]:
        image=rng.integers(0,256,(h,w,3),dtype=np.uint8)
        payload,mapping=prepare_bgr(image)
        ref=LetterBox(new_shape=(416,416),auto=False,scale_fill=False,scaleup=True,center=True)(image=image)
        actual=np.frombuffer(payload,dtype=np.uint8).reshape(416,416,3)
        err=int(np.max(np.abs(actual.astype(int)-ref[:,:,::-1].astype(int))))
        assert err==0,(h,w,err)
        prep.append({'source_shape':[h,w],'max_pixel_error':err})
    DecodeParity.setUpClass();check=DecodeParity();reports=[]
    try:
        with torch.inference_mode():
            for row in rows:
                image=load_bgr(manifest.parent/row['image']);payload,mapping=prepare_bgr(image)
                tensor=torch.from_numpy(np.frombuffer(payload,dtype=np.uint8).copy().reshape(416,416,3)).permute(2,0,1).unsqueeze(0).float()/255
                captured=[]
                hook=model.model[-1].register_forward_pre_hook(lambda mod,args:captured.extend(args[0]))
                predicted=model(tensor)[0];hook.remove();head=model.model[-1]
                raw=[torch.cat((head.cv2[i](v),head.cv3[i](v)),1).numpy() for i,v in enumerate(captured)]
                c=check.compare(raw,[8,16,32],confidence=.001,iou=.45,input_size=416)
                official=non_max_suppression(predicted.clone(),conf_thres=.001,iou_thres=.45,multi_label=True,max_det=300,nc=18)[0].numpy()
                ours=decode_raw_heads(raw,confidence=.001,iou=.45,max_detections=300)
                assert len(ours)==len(official),(row['id'],len(ours),len(official))
                maxerr=0.0
                for actual,expected in zip(ours,official):
                    assert actual.class_id==int(expected[5]),row['id']
                    vals=np.array([actual.x1,actual.y1,actual.x2,actual.y2])*416
                    err=float(np.max(np.abs(vals-expected[:4])))
                    assert err<.001 and abs(actual.score-float(expected[4]))<1e-6,(row['id'],err)
                    maxerr=max(maxerr,err)
                reports.append({'image':row['id'],'detections':len(c),'max_official_box_error_pixels':maxerr})
    finally: DecodeParity.tearDownClass()
    report={'status':'PASS','preprocess':prep,'actual_checkpoint_images':reports,
            'python_c_parity':'PASS','official_decode_nms':'PASS','confidence':.001,'nms_iou':.45,'max_det':300,
            'normalization':'RGB /255 exactly once; desktop transports uint8',
            'complete_validation_ap_evaluated':False}
    (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))


if __name__=='__main__':main()
