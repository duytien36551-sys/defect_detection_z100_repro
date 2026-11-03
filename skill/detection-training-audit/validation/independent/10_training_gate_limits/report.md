# Training and model acceptance — 10_training_gate_limits

## Conclusion

**Training completion: PASS for the requested epoch-200 cutoff. Business/deployment acceptance: NOT EVALUATED.** The passed acceptance verifies the training stop/checkpoint state, not product quality. Test, INT8, board, normal-image false-alarm and business gate results are absent or unevaluable.

## Completion and model selection

- 200 epochs of the original 300-epoch schedule completed; reason says user requested epoch-200 cutoff and original LR/mosaic schedules were preserved. Epoch 201 did not complete.
- Best selection: maximum frozen validation AP50:95; epoch 200. Declared best-weight SHA-256 `2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6` agrees with `final_acceptance.json`. Weight bytes are absent, so this review did not rehash them.
- Checkpoint state: epoch0=199, optimizer states=183, scheduler last epoch=199, live state/EMA/RNG present; split unchanged; both evaluations use the same declared frozen weight; no training process remains.
- The two records give different best-weight path spellings (`user_finish_epoch200_best.pt` vs `best.pt`) with the same declared hash. Actual alias/file identity is unverified.

## Frozen-weight validation

Augmented validation: 800 images, 2295 targets, 0 normal images; AP50 **0.968636**, AP50:95 **0.797333**. Evaluation records `imgsz=640`, actual input `[3,672,672]`, batch 16, rect true; fixed point conf=.25, NMS IoU=.45, match IoU=.5, max_det=300, same-class greedy one-to-one matching, no class filtering. Independently summed micro TP/FP/FN **2156/124/139**, P/R/F1 **0.945614/0.939434/0.942514**.

### Augmented validation per-class results

| ID | Class | Targets | AP50 | AP50:95 | P@.25 | R@.25 | TP | FP | FN |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | PIN_破损 | 680 | 0.9713 | 0.8051 | 0.9516 | 0.9544 | 649 | 33 | 31 |
| 1 | PIN_裂痕 | 392 | 0.9168 | 0.7163 | 0.8941 | 0.8827 | 346 | 41 | 46 |
| 2 | PIN_击穿 | 84 | 0.9950 | 0.9769 | 1.0000 | 1.0000 | 84 | 0 | 0 |
| 3 | PIN_薄膜破损 | 361 | 0.9704 | 0.7922 | 0.9402 | 0.9584 | 346 | 22 | 15 |
| 4 | PIN_电极缺失 | 141 | 0.9950 | 0.8802 | 1.0000 | 1.0000 | 141 | 0 | 0 |
| 5 | PIN_异物 | 100 | 0.9850 | 0.8653 | 1.0000 | 0.9900 | 99 | 0 | 1 |
| 6 | PIN_有机物污染 | 353 | 0.9044 | 0.7534 | 0.9224 | 0.8754 | 309 | 26 | 44 |
| 7 | PIN_部分缺失 | 78 | 0.9950 | 0.7337 | 1.0000 | 1.0000 | 78 | 0 | 0 |
| 8 | PIN_冗余 | 106 | 0.9849 | 0.6531 | 0.9811 | 0.9811 | 104 | 2 | 2 |

Lowest AP50:95 is PIN_冗余 (0.6531; 106 targets), then PIN_裂痕 (0.7163; 392) and PIN_部分缺失 (0.7337; 78). Lowest fixed-point recall is PIN_有机物污染 (0.8754; 353) and PIN_裂痕 (0.8827; 392). Smallest target count is PIN_部分缺失: 78.

### Original validation subset

160 images, 476 targets, 0 normal images; AP50 **0.971857**, AP50:95 **0.812918**. Micro TP/FP/FN **450/27/26**, P/R/F1 **0.943396/0.945378/0.944386**. This is a different denominator/set, not a historical baseline. PIN_击穿 has only 3 targets in this subset.

| ID | Class | Targets | AP50 | AP50:95 | P@.25 | R@.25 | TP | FP | FN |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | PIN_破损 | 143 | 0.9711 | 0.8232 | 0.9586 | 0.9720 | 139 | 6 | 4 |
| 1 | PIN_裂痕 | 86 | 0.9312 | 0.7340 | 0.8837 | 0.8837 | 76 | 10 | 10 |
| 2 | PIN_击穿 | 3 | 0.9950 | 0.9950 | 1.0000 | 1.0000 | 3 | 0 | 0 |
| 3 | PIN_薄膜破损 | 79 | 0.9720 | 0.8110 | 0.9390 | 0.9747 | 77 | 5 | 2 |
| 4 | PIN_电极缺失 | 31 | 0.9950 | 0.8850 | 1.0000 | 1.0000 | 31 | 0 | 0 |
| 5 | PIN_异物 | 22 | 0.9950 | 0.9174 | 1.0000 | 1.0000 | 22 | 0 | 0 |
| 6 | PIN_有机物污染 | 72 | 0.8974 | 0.7422 | 0.9118 | 0.8611 | 62 | 6 | 10 |
| 7 | PIN_部分缺失 | 17 | 0.9950 | 0.7374 | 1.0000 | 1.0000 | 17 | 0 | 0 |
| 8 | PIN_冗余 | 23 | 0.9950 | 0.6710 | 1.0000 | 1.0000 | 23 | 0 | 0 |

## Gate outcomes

| Gate | Status | Basis |
|---|---|---|
| Requested training cutoff | PASS | Acceptance says 1–200 continuous, no 201, checkpoint/state present, no processes. |
| Best checkpoint | Supported as reported | Frozen-validation AP50:95 selection; epoch 200 and same declared SHA; binary absent. |
| Business quality | NOT EVALUATED | `business_acceptance=not_evaluated`; no business thresholds in fixture. |
| Normal false-alarm rate | NOT EVALUABLE | Both sets have 0 normal images. Do not report 0%. |
| Test | NOT EVALUATED | `test_used=false`; no test metrics/counts. |
| INT8 | NOT EVALUATED | `int8_evaluated=false`; no measurements. |
| Board | NOT EVALUATED | `board_evaluated=false`; no board metrics/latency. |
| Loss/overfit | NOT EVALUATED | Training-quality metrics flag is true; no loss curves. |

Report says 800 augmented validation images arise from 160 source groups; physical-chip/batch independence is not verified. It also says no fair direct comparison to historical validation splits. Initialization is random-from-architecture-only with `pretrained=false`; no baseline is provided. Test/split/threshold were not changed.

The machine-readable report duplicates all per-class values for both validation tables. Evidence keys/lines are in `report.json`.
