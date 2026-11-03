# Export and INT8 review — 04_parity_quality_gate

## Conclusion

**Quality acceptance: FAIL as recorded.** `accuracy_accepted=false`, `int8_comparison_pass=false`. The record reports `float_comparison_pass=true` and identical official/float AP fields, but no raw tensor or contract is provided to independently establish numeric/byte implementation parity. No C/RTL or actual-board evidence is present.

## Validation scope and aggregate AP

Domain `pin`, 9 classes, 800 images, `full_validation=True`, `per_task_limit=null`, elapsed 1148.703 s. Checkpoint SHA-256 is report-declared as `603853a8ec851b32578d79d34ddaeb9487f1c7924dc815d557565725f275a034`; checkpoint bytes absent.

| Backend | Images | AP50 | AP50:95 | Record status |
|---|---:|---:|---:|---|
| Official | 800 | 0.970058 | 0.763839 | Reference fields |
| Float export | 800 | 0.970058 | 0.763839 | Flag pass; metrics match official |
| INT8 | 800 | 0.965558 | 0.718525 | Flag fail |

INT8 minus float: **-0.450 percentage points AP50**, **-4.531 percentage points AP50:95**.

## Per-class metrics

| ID | Class | Targets | Float AP50 | INT8 AP50 | Δ50 pp | Float AP50:95 | INT8 AP50:95 | Δ95 pp |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | PIN_破损 | 680 | 0.9727 | 0.9614 | -1.131 | 0.7442 | 0.6890 | -5.526 |
| 1 | PIN_裂痕 | 392 | 0.9158 | 0.9080 | -0.785 | 0.6664 | 0.6128 | -5.353 |
| 2 | PIN_击穿 | 84 | 0.9950 | 0.9950 | 0.000 | 0.9687 | 0.9469 | -2.174 |
| 3 | PIN_薄膜破损 | 361 | 0.9790 | 0.9744 | -0.455 | 0.7432 | 0.6977 | -4.551 |
| 4 | PIN_电极缺失 | 141 | 0.9950 | 0.9950 | 0.000 | 0.8599 | 0.8447 | -1.526 |
| 5 | PIN_异物 | 100 | 0.9850 | 0.9850 | 0.000 | 0.8540 | 0.8125 | -4.146 |
| 6 | PIN_有机物污染 | 353 | 0.8985 | 0.8889 | -0.962 | 0.7186 | 0.6506 | -6.802 |
| 7 | PIN_部分缺失 | 78 | 0.9949 | 0.9949 | 0.000 | 0.6847 | 0.6259 | -5.877 |
| 8 | PIN_冗余 | 106 | 0.9946 | 0.9875 | -0.717 | 0.6349 | 0.5866 | -4.827 |

Largest AP50:95 drops: PIN_有机物污染 −6.802 pp; PIN_部分缺失 −5.877 pp; PIN_破损 −5.526 pp.

## Distinguish the evidence

- **Float export:** recorded flag pass and official/float AP equality; not raw output equality.
- **INT8 model quality:** measured AP is lower; record rejects accuracy acceptance. The underlying gate threshold is not supplied.
- **Implementation parity:** unassessed beyond report flags; no reference/C/RTL/board outputs, tensor dtype/shape/layout/scale contract, or first divergent location.
- **Board deployment:** not evidenced; no board result or firmware/bitstream identity.

No threshold was changed and validation was not rerun. JSON pointers and source lines are in `report.json`.
