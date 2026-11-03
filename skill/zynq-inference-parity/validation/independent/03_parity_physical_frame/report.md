# Independent review: 03_parity_physical_frame

## Scope

Read only this case's task and inputs, plus the required zynq-inference-parity skill.md and references/workflow.md. No board operation was performed.

## Findings

The supplied record labels the run PASS_ONE_PHYSICAL_FULL_MODEL_FRAME_613200_BYTES_EXACT. It also sets release_eligible, accuracy_accepted, and fps_accepted to false. This represents one fixed validation image from a provisional baseline INT8 package.

| Contract item | Evidence and independent check |
|---|---|
| Input | Domain pin, configured input size 640, one validation image. The image itself, its hash, dimensions, dtype, channel order, and preprocessing details are absent. |
| Output logical bytes | 613,200 bytes, as declared in first_frame_summary.json. SHA-256 recomputed over the first 613,200 bytes is 719c01a206b9ceeef7ed9d8c5bfc82c8edc12fd6294c6d8a342ff24ab1fbd707, equal to the declared expected head hash. |
| Captured file | 613,248 bytes; full-file SHA-256 is 8661127d8715c6cd4c3c17611581d4b02d1a7f9483aabcefe2576a7a226d3555. The final 48 bytes are all zero. |
| Reported mismatch count | Board result says zero. The expected raw reference bytes are not supplied, so this review cannot recompute a two-file byte mismatch count. It independently confirms only that the captured logical-prefix hash matches the reported expected hash. |
| Tensor representation | dtype, shape, layout, byte order, and scales are absent. Do not infer them from the byte count. |

The capture is 48 bytes longer than the stated logical output. This explains why the full-file hash differs from the logical-prefix hash. The comparison boundary is the 613,200-byte logical length stated in the summary.

Execution record: 163 graph nodes, two detections, 94 tile loads, 6,319 tile runs, stage complete and model/DMA error words zero. The recorded final register snapshot lists txsr=4098, rxsr=4098, tile=32. The summary says both CPUs stopped and DMA idle/error-clear after this one-shot.

## Timing

The timer frequency is 333,333,343 Hz from the matched BSP, described as generated CPU clock/2; the oscillator was not independently measured. Phase values recomputed from board_result.json ticks are:

| Phase | Ticks | Recomputed milliseconds |
|---|---:|---:|
| Preprocess | 9,219,779 | 27.659 |
| Graph | 2,134,518,062 | 6,403.554 |
| Dequantization | 5,411,701 | 16.235 |
| Decode | 43,881,029 | 131.643 |
| Total | 2,193,031,570 | 6,579.095 |

The summary reports node interval sum 6,389.339 ms inside the 6,403.554 ms graph phase. Node intervals are not the pipeline total. The record explicitly says full-pipeline transport and sustained FPS were not measured.

## Limits

- One image does not establish overall accuracy, P50/P95, sustained throughput, or release readiness.
- Input image and expected output reference binaries are missing. Hashes listed for the graph, diagnostics, result, and xparameters are references in the summary; those files were not supplied or checked.
- Exact input preprocessing and output tensor dtype/shape/layout/endianness/scale remain unknown.
- The zero mismatch count is a source-record claim; it was not recreated from both byte streams.

## Skills and operation log

Loaded zynq-inference-parity version 1.0.0-rc1 and its references/workflow.md. Read the task.md and three files under this case's inputs. Used standard-library JSON parsing, arithmetic, byte slicing, zero-byte counting, and SHA-256. No board, network, training, model selection, or weight loading action was taken. Reports were written only under skill/validation/independent_normal_20261025.

## Input hashes

The report JSON records pre-report-write and post-report-write SHA-256 values for all three inputs and whether they remained unchanged.