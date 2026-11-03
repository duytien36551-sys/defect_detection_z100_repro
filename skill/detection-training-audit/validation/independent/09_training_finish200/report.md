# Independent review: 09_training_finish200

## Scope and selection

Loaded detection-training-audit version 1.0.0-rc1 and its references/workflow.md. The acceptance record says epochs 1–200 completed, no epoch 201 completed, and the user requested an epoch-200 cutoff while preserving the original 300-epoch LR and mosaic schedules. Recorded selection rule: maximum frozen validation AP50:95. The contiguous 200-row CSV has its maximum reported metrics/mAP50-95(B) of 0.79723 at epoch 200. This supports the documented selection; I did not select another checkpoint.

## Weights, checkpoint, initialization

The reported best path is <project-root>\pin_paperstyle300e_20261021\runs\pin\weights\user_finish_epoch200_best.pt with declared SHA-256 2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6. The validation alias path is <project-root>\pin_paperstyle300e_20261021\runs\pin\weights\best.pt; its reported SHA is the same. Acceptance and audit repeat that SHA. The weight file is not among the inputs, so the SHA consistency is cross-report only. Checkpoint epoch0=199, scheduler last epoch=199, optimizer states reported=183, live state/EMA/RNG present. Checkpoint SHA is 5f18ce20c1d4a95029accd213bb90e27833af9cacc18aa49ea311f0de0fd8a92; checkpoint bytes were not provided. Initialization is random from architecture only, pretrained=false, seed 20261021, nc=9, 3,012,603 parameters.

## Split evidence

The split manifest has 8000 rows; its recomputed SHA-256 matches the audit declaration. Recorded group IDs do not cross train/validation/test (0 overlaps in the manifest). This does not prove physical-chip independence.

| Split | Images | Groups | Original | New augmentation | Prior Albumentations |
|---|---:|---:|---:|---:|---:|
| train | 6400 | 1284 | 1284 | 5011 | 105 |
| val | 800 | 160 | 160 | 625 | 15 |
| test | 800 | 162 | 162 | 628 | 10 |

Augmented validation: 800 images, 0 normal images, 2295 targets; original subset: 160 images, 0 normals, 476 targets.

## Augmented validation

AP summary: mAP50=0.968636, mAP50:95=0.797333. AP evaluation uses imgsz=640, rect=True, actual shape [3, 672, 672], conf=0.001, NMS IoU=0.45, max_det=300.

Fixed micro point: conf=0.25, NMS IoU=0.45, match IoU=0.5, max_det=300, classes_filtered=False; Installed Ultralytics same-class IoU greedy one-to-one matching, recomputed after confidence filtering. TP=2156, FP=124, FN=139, P=0.945614, R=0.939434, F1=0.942514.

AP columns below are threshold-swept AP; fixed P/R/TP/FP/FN columns use conf=0.25 and are not the AP operating point.

### All 9 classes: augmented validation

| ID | Class | Targets | AP50 | AP50:95 | Fixed TP | FP | FN | Fixed P | Fixed R |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | PIN_破损 | 680 | 0.9713 | 0.8051 | 649 | 33 | 31 | 0.9516 | 0.9544 |
| 1 | PIN_裂痕 | 392 | 0.9168 | 0.7163 | 346 | 41 | 46 | 0.8941 | 0.8827 |
| 2 | PIN_击穿 | 84 | 0.9950 | 0.9769 | 84 | 0 | 0 | 1.0000 | 1.0000 |
| 3 | PIN_薄膜破损 | 361 | 0.9704 | 0.7922 | 346 | 22 | 15 | 0.9402 | 0.9584 |
| 4 | PIN_电极缺失 | 141 | 0.9950 | 0.8802 | 141 | 0 | 0 | 1.0000 | 1.0000 |
| 5 | PIN_异物 | 100 | 0.9850 | 0.8653 | 99 | 0 | 1 | 1.0000 | 0.9900 |
| 6 | PIN_有机物污染 | 353 | 0.9044 | 0.7534 | 309 | 26 | 44 | 0.9224 | 0.8754 |
| 7 | PIN_部分缺失 | 78 | 0.9950 | 0.7337 | 78 | 0 | 0 | 1.0000 | 1.0000 |
| 8 | PIN_冗余 | 106 | 0.9849 | 0.6531 | 104 | 2 | 2 | 0.9811 | 0.9811 |

## Original subset

AP summary: mAP50=0.971857, mAP50:95=0.812918. Fixed point TP=450, FP=27, FN=26, P=0.943396, R=0.945378, F1=0.944386.

### All 9 classes: original subset

| ID | Class | Targets | AP50 | AP50:95 | Fixed TP | FP | FN | Fixed P | Fixed R |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | PIN_破损 | 143 | 0.9711 | 0.8232 | 139 | 6 | 4 | 0.9586 | 0.9720 |
| 1 | PIN_裂痕 | 86 | 0.9312 | 0.7340 | 76 | 10 | 10 | 0.8837 | 0.8837 |
| 2 | PIN_击穿 | 3 | 0.9950 | 0.9950 | 3 | 0 | 0 | 1.0000 | 1.0000 |
| 3 | PIN_薄膜破损 | 79 | 0.9720 | 0.8110 | 77 | 5 | 2 | 0.9390 | 0.9747 |
| 4 | PIN_电极缺失 | 31 | 0.9950 | 0.8850 | 31 | 0 | 0 | 1.0000 | 1.0000 |
| 5 | PIN_异物 | 22 | 0.9950 | 0.9174 | 22 | 0 | 0 | 1.0000 | 1.0000 |
| 6 | PIN_有机物污染 | 72 | 0.8974 | 0.7422 | 62 | 6 | 10 | 0.9118 | 0.8611 |
| 7 | PIN_部分缺失 | 17 | 0.9950 | 0.7374 | 17 | 0 | 0 | 1.0000 | 1.0000 |
| 8 | PIN_冗余 | 23 | 0.9950 | 0.6710 | 23 | 0 | 0 | 1.0000 | 1.0000 |

## Loss curves and overfit observation

Full per-epoch train/validation loss and metric series is preserved in report.json under findings.epoch_history.

| Loss | Epoch 1 | Epoch 200 | Minimum | Min epoch |
|---|---:|---:|---:|---:|
| train/box_loss | 3.97144 | 0.80733 | 0.80733 | 200 |
| train/cls_loss | 4.75494 | 0.48321 | 0.48171 | 197 |
| train/dfl_loss | 3.58841 | 1.02473 | 1.02101 | 198 |
| val/box_loss | 3.60598 | 0.71874 | 0.71874 | 200 |
| val/cls_loss | 4.67382 | 0.40112 | 0.40112 | 200 |
| val/dfl_loss | 3.36192 | 1.01816 | 1.01816 | 200 |

Logged losses fall across the run; these rows show no endpoint train/validation loss divergence, and validation losses reach their minima at epoch 200. This is not quality acceptance: the validation set includes augmented descendants, has no normal images, and physical-device independence is unverified.

## Acceptance gaps

- Normal-image false-alarm rate is not evaluable because normal_images=0; it is not 0%.
- Test was unused and has no reported metrics. This respects frozen selection but leaves independent test acceptance incomplete.
- INT8 and board evaluation are false; business acceptance is not_evaluated. No float-to-INT8 percentage-point loss or real-board P50/P95 is available.
- No fair baseline comparison is supplied; report says historical validation splits are not directly comparable.
- Training imgsz/config and per-class train/test target counts are absent. The 640 evaluation setting produced actual shape [3,672,672].
- Remaining-process and stopped-PID statements are historical report fields; no current process inspection was done.

## Limits and operation log

The weight and checkpoint binaries, labels, and original images were not included in the allowed inputs. I did not open external result directories or inspect referenced files. Only the requested inputs and skill instructions were read; no weight was loaded, no model was reselected, and no training/board action was taken.

## Input hashes

Pre-report and post-report SHA-256 values for all five inputs are stored in report.json; all_unchanged records the comparison.
