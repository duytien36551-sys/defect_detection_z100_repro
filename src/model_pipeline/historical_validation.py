"""Validation-only PIN640 entry point with complete zero-prediction class metrics."""
import os
from pathlib import Path
import sys

for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from ultralytics.utils.metrics import ap_per_class
from deployment.candidates.pin640 import evaluate_deployment as evaluator


def summarize_complete(image_stats,names):
    if not image_stats:raise ValueError('No validation images')
    classes=set(range(len(names)));tp=[];conf=[];pred=[];target=[]
    for row in image_stats:
        t=np.asarray(row['tp'],dtype=bool).reshape(-1,10)
        c=np.asarray(row['conf'],dtype=np.float64).reshape(-1)
        p=np.asarray(row['pred_cls'],dtype=np.int64).reshape(-1)
        g=np.asarray(row['target_cls'],dtype=np.int64).reshape(-1)
        if len(t)!=len(c) or len(p)!=len(c) or not set(p)<=classes or not set(g)<=classes:
            raise ValueError('Invalid validation statistics')
        if not np.isfinite(c).all() or np.any(c<0) or np.any(c>1):raise ValueError('Invalid confidence')
        tp.append(t);conf.append(c);pred.append(p);target.append(g)
    tp=np.concatenate(tp);conf=np.concatenate(conf);pred=np.concatenate(pred);target=np.concatenate(target)
    support={i:int(np.count_nonzero(target==i)) for i in classes}
    if any(value==0 for value in support.values()):raise ValueError('Validation class support is missing')
    if len(pred):
        *_,ap,class_index,_p,_r,_f,_x,_prec=ap_per_class(tp,conf,pred,target,plot=False,names=dict(enumerate(names)))
        by_id={int(i):ap[k] for k,i in enumerate(class_index)}
    else:by_id={}
    rows={name:dict(class_id=i,ap50=float(by_id.get(i,np.zeros(10))[0]),
                    ap50_95=float(np.mean(by_id.get(i,np.zeros(10)))),ground_truth_count=support[i])
          for i,name in enumerate(names)}
    return dict(images=len(image_stats),ap50=float(np.mean([x['ap50'] for x in rows.values()])),
                ap50_95=float(np.mean([x['ap50_95'] for x in rows.values()])),per_class=rows)


def main():
    # The imported CLI only selects manifest val rows. No test mode is added.
    evaluator.summarize_single_domain=summarize_complete
    evaluator.main()


if __name__=='__main__':main()
