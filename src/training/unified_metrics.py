"""Task-specific AP from per-image Ultralytics detection matches.

Each image row contains its task, tp[N,10] for IoU .50:.95, confidence,
predicted class IDs, and all target class IDs. Both models use this reducer.
"""
from __future__ import annotations

import numpy as np
from ultralytics.utils.metrics import ap_per_class


TASK_CLASSES = {"pcb": tuple(range(9)), "pin": tuple(range(9, 18))}


def summarize_from_images(image_stats, names):
    """Compute AP for the nine classes of each task on that task's images."""
    if len(names) != 18:
        raise ValueError("Expected eighteen ordered class names")
    rows = list(image_stats)
    if any(row.get("task") not in TASK_CLASSES for row in rows):
        raise ValueError("Each validation image must have task pcb or pin")
    report = {}
    for task, class_ids in TASK_CLASSES.items():
        selected = [row for row in rows if row["task"] == task]
        if not selected:
            raise ValueError(f"No validation images for {task}")
        tp_parts, conf_parts, pred_parts, target_parts = [], [], [], []
        for row in selected:
            tp = np.asarray(row["tp"], dtype=bool).reshape(-1, 10)
            conf = np.asarray(row["conf"], dtype=np.float64).reshape(-1)
            pred = np.asarray(row["pred_cls"], dtype=np.int64).reshape(-1)
            target = np.asarray(row["target_cls"], dtype=np.int64).reshape(-1)
            if len(tp) != len(conf) or len(conf) != len(pred):
                raise ValueError("Prediction stats have inconsistent lengths")
            if not np.isfinite(conf).all() or np.any((conf < 0) | (conf > 1)):
                raise ValueError("Invalid confidence")
            if np.any(~np.isin(target, class_ids)):
                raise ValueError(f"Off-task target on {task} image")
            tp_parts.append(tp)
            conf_parts.append(conf)
            pred_parts.append(pred)
            target_parts.append(target)
        tp = np.concatenate(tp_parts)
        conf = np.concatenate(conf_parts)
        pred = np.concatenate(pred_parts)
        target = np.concatenate(target_parts)
        counts = {cid: int(np.count_nonzero(target == cid)) for cid in class_ids}
        if any(count == 0 for count in counts.values()):
            raise ValueError(f"Missing target class in {task} validation")
        # ap_per_class uses the exact interpolation and class aggregation of
        # the installed Ultralytics validator. Its AP rows follow class_index.
        *_, ap, class_index, _p_curve, _r_curve, _f1_curve, _x, _prec = ap_per_class(
            tp, conf, pred, target, plot=False, names={i: names[i] for i in range(18)}
        )
        by_id = {int(cid): ap[i] for i, cid in enumerate(class_index)}
        per_class = {
            names[cid]: {"class_id": cid, "ap50": float(by_id[cid][0]),
                         "ap50_95": float(np.mean(by_id[cid])), "ground_truth_count": counts[cid]}
            for cid in class_ids
        }
        report[task] = {
            "images": len(selected), "ap50": float(np.mean([per_class[names[c]]["ap50"] for c in class_ids])),
            "ap50_95": float(np.mean([per_class[names[c]]["ap50_95"] for c in class_ids])),
            "per_class": per_class,
        }
    return report
