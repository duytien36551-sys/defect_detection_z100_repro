"""YOLOv8n raw-head decoder for the 640 px, batch-one deployment graph.

Each head is contiguous NCHW float32 with [4*reg_max DFL logits, class logits].
Returned xyxy coordinates are normalized to model width/height. Letterbox
projection is a separate, explicit operation so NMS sees the original raw box.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    class_id: int


@dataclass(frozen=True)
class Letterbox:
    original_width: int
    original_height: int
    input_width: int
    input_height: int
    scale_x: float
    scale_y: float
    pad_left: float
    pad_top: float


def _sigmoid(logits: np.ndarray) -> np.ndarray:
    positive = logits >= 0
    result = np.empty_like(logits, dtype=np.float64)
    result[positive] = 1.0 / (1.0 + np.exp(-logits[positive]))
    exp_values = np.exp(logits[~positive])
    result[~positive] = exp_values / (1.0 + exp_values)
    return result


def _nms_for_class(boxes: np.ndarray, scores: np.ndarray, sequences: np.ndarray,
                   iou_threshold: float) -> np.ndarray:
    order = np.lexsort((sequences, -scores))
    keep: list[int] = []
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while order.size:
        current = int(order[0])
        keep.append(current)
        remaining = order[1:]
        if not remaining.size:
            break
        intersection_left = np.maximum(boxes[current, 0], boxes[remaining, 0])
        intersection_top = np.maximum(boxes[current, 1], boxes[remaining, 1])
        intersection_right = np.minimum(boxes[current, 2], boxes[remaining, 2])
        intersection_bottom = np.minimum(boxes[current, 3], boxes[remaining, 3])
        intersection = np.maximum(0.0, intersection_right - intersection_left) * np.maximum(
            0.0, intersection_bottom - intersection_top
        )
        union = areas[current] + areas[remaining] - intersection
        iou = np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)
        order = remaining[iou <= iou_threshold]
    return np.asarray(keep, dtype=np.int64)


def decode_raw_heads(
    heads: Sequence[np.ndarray],
    *,
    strides: Sequence[int] = (8, 16, 32),
    input_width: int = 640,
    input_height: int = 640,
    classes: int = 9,
    reg_max: int = 16,
    confidence: float = 0.001,
    iou: float = 0.45,
    max_detections: int = 300,
    multi_label: bool = True,
    class_confidence: Sequence[float] | None = None,
) -> list[Detection]:
    """Decode all classes, class-aware NMS, then apply the global result cap.

    `multi_label=True` mirrors the joint evaluation: each cell can contribute
    more than one class. If provided, `class_confidence` replaces the global
    confidence threshold for each class. No per-class output cap is applied.
    """
    if not heads or len(heads) != len(strides) or input_width <= 0 or input_height <= 0:
        raise ValueError("heads, strides, and positive input dimensions are required")
    if classes <= 0 or not 1 < reg_max <= 64 or max_detections <= 0:
        raise ValueError("invalid classes, reg_max, or max_detections")
    if not np.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be within [0,1]")
    if not np.isfinite(iou) or not 0 <= iou <= 1:
        raise ValueError("iou must be within [0,1]")
    if class_confidence is None:
        class_thresholds = np.full(classes, confidence, dtype=np.float64)
    else:
        class_thresholds = np.asarray(class_confidence, dtype=np.float64)
        if (class_thresholds.shape != (classes,) or
                not np.isfinite(class_thresholds).all() or
                np.any((class_thresholds < 0) | (class_thresholds > 1))):
            raise ValueError("class_confidence must contain one finite [0,1] threshold per class")

    all_boxes: list[np.ndarray] = []
    all_scores: list[np.ndarray] = []
    all_classes: list[np.ndarray] = []
    all_sequences: list[np.ndarray] = []
    cell_offset = 0
    for head, stride in zip(heads, strides):
        raw = np.asarray(head, dtype=np.float32)
        if raw.ndim != 4 or raw.shape[0] != 1 or raw.shape[1] != 4 * reg_max + classes:
            raise ValueError("raw heads must have shape (1, 4*reg_max+classes, H, W)")
        height, width = raw.shape[2:]
        if stride <= 0 or width * stride != input_width or height * stride != input_height:
            raise ValueError("head shape and stride do not match model input")
        cells = height * width
        distributions = raw[0, : 4 * reg_max].reshape(4, reg_max, cells)
        valid = np.isfinite(distributions).all(axis=(0, 1))
        stable = np.where(valid[None, None, :], distributions, 0.0).astype(np.float64)
        stable -= stable.max(axis=1, keepdims=True)
        probabilities = np.exp(stable)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        distance = np.einsum("brn,r->bn", probabilities, np.arange(reg_max), optimize=True)
        grid_y, grid_x = np.indices((height, width))
        anchor_x = (grid_x.ravel() + 0.5) * stride
        anchor_y = (grid_y.ravel() + 0.5) * stride
        boxes = np.column_stack((
            anchor_x - distance[0] * stride,
            anchor_y - distance[1] * stride,
            anchor_x + distance[2] * stride,
            anchor_y + distance[3] * stride,
        ))
        valid &= (boxes[:, 2] > boxes[:, 0]) & (boxes[:, 3] > boxes[:, 1])
        class_logits = raw[0, 4 * reg_max:].reshape(classes, cells).T
        finite_class = np.isfinite(class_logits)
        class_scores = _sigmoid(np.where(finite_class, class_logits, -np.inf))
        if multi_label:
            cell_ids, class_ids = np.nonzero(valid[:, None] & finite_class &
                                             (class_scores >= class_thresholds[None, :]))
        else:
            best = class_scores.argmax(axis=1)
            cell_ids = np.nonzero(valid & finite_class[np.arange(cells), best] &
                                  (class_scores[np.arange(cells), best] >= class_thresholds[best]))[0]
            class_ids = best[cell_ids]
        if cell_ids.size:
            all_boxes.append(boxes[cell_ids])
            all_scores.append(class_scores[cell_ids, class_ids])
            all_classes.append(class_ids.astype(np.int32))
            all_sequences.append((cell_offset + cell_ids) * classes + class_ids)
        cell_offset += cells
    if not all_boxes:
        return []
    boxes = np.concatenate(all_boxes)
    scores = np.concatenate(all_scores)
    class_ids = np.concatenate(all_classes)
    sequences = np.concatenate(all_sequences)
    kept: list[np.ndarray] = []
    for cls in range(classes):
        members = np.nonzero(class_ids == cls)[0]
        if members.size:
            kept.append(members[_nms_for_class(boxes[members], scores[members],
                                               sequences[members], iou)])
    selected = np.concatenate(kept)
    selected = selected[np.lexsort((sequences[selected], -scores[selected]))][:max_detections]
    return [Detection(float(boxes[i, 0] / input_width), float(boxes[i, 1] / input_height),
                      float(boxes[i, 2] / input_width), float(boxes[i, 3] / input_height),
                      float(scores[i]), int(class_ids[i])) for i in selected]


def filter_classes(detections: Sequence[Detection], first_class: int,
                   class_count: int) -> list[Detection]:
    """Filter one task after all-class NMS and global cap."""
    if first_class < 0 or class_count <= 0:
        raise ValueError("invalid task class range")
    return [item for item in detections
            if first_class <= item.class_id < first_class + class_count]


def project_box(detection: Detection, letterbox: Letterbox) -> Detection:
    """Map normalized model coordinates to clipped original-image pixels."""
    if (letterbox.original_width <= 0 or letterbox.original_height <= 0 or
            letterbox.input_width <= 0 or letterbox.input_height <= 0 or
            not np.isfinite((letterbox.scale_x, letterbox.scale_y,
                             letterbox.pad_left, letterbox.pad_top)).all() or
            letterbox.scale_x <= 0 or letterbox.scale_y <= 0):
        raise ValueError("invalid letterbox metadata")
    if not np.isfinite((detection.x1, detection.y1, detection.x2, detection.y2)).all():
        raise ValueError("nonfinite box")
    return Detection(
        float(np.clip((detection.x1 * letterbox.input_width - letterbox.pad_left) /
                      letterbox.scale_x, 0, letterbox.original_width)),
        float(np.clip((detection.y1 * letterbox.input_height - letterbox.pad_top) /
                      letterbox.scale_y, 0, letterbox.original_height)),
        float(np.clip((detection.x2 * letterbox.input_width - letterbox.pad_left) /
                      letterbox.scale_x, 0, letterbox.original_width)),
        float(np.clip((detection.y2 * letterbox.input_height - letterbox.pad_top) /
                      letterbox.scale_y, 0, letterbox.original_height)),
        detection.score, detection.class_id,
    )
