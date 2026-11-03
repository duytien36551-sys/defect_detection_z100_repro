# Independent review: 05_pspl_profile

## Scope

Read only this case's task and inputs, plus the required zynq-ps-pl-performance skill.md and references/workflow.md. No board operation was performed.

## Run identity and reported result

The profile record is dated 2026-10-23 05:23:27 UTC. It identifies ELF SHA-256 f008b35d15c020c3e619867da19cf0f3a12c43213cd12e18471661b6c27e97aa, input SHA-256 f82d6ce4ad170ec4859a49f405d6a0b7ca2cdbd93b5e57142a556a92ccd750e0, and expected/captured head hash 719c01a206b9ceeef7ed9d8c5bfc82c8edc12fd6294c6d8a342ff24ab1fbd707 with a reported mismatch count of zero. The record marks release and FPS unaccepted. No raw input, output, or ELF binary is included, so these are record claims in this review.

## Operator interval aggregation

This is an actual single-frame aggregation, expressly not an FPS measurement. The profile says these are distinct node intervals and no nested counters were summed.

| Operation | Nodes | Aggregate ms |
|---|---:|---:|
| conv | 63 | 5,538.812 |
| silu | 57 | 212.702 |
| slice | 16 | 112.216 |
| add | 6 | 192.832 |
| concat | 16 | 91.508 |
| maxpool | 3 | 131.042 |
| upsample | 2 | 54.413 |
| Non-convolution total | — | 794.713 |
| Sum of distinct operation groups | 163 | 6,333.525 |

Convolution is the largest group. Non-convolution intervals are about 12.5% of the distinct-node sum. Add node 12 is the largest listed non-convolution node (71.446 ms); maxpool nodes 70–72 total 131.042 ms.

## Phase timing and nested counters

Timer is 333,333,343 Hz. Pipeline ticks recompute as follows:

| Phase | Ticks | Recomputed ms |
|---|---:|---:|
| Preprocess | 9,190,385 | 27.571 |
| Graph | 2,115,192,680 | 6,345.578 |
| Dequantization | 5,409,325 | 16.228 |
| Decode | 36,084,684 | 108.254 |
| Total | 2,165,877,953 | 6,497.634 |

The profile also records 94 load calls, 6,319 run calls and 6,413 DMA calls. Load plus run bytes are 82,883,776, equal to reported TX bytes; reported RX bytes are 57,057,860. Selected nested counters include run-transfer 2,009.721 ms, DMA-poll 1,525.168 ms, DMA-prepare 404.598 ms, response-parse 416.506 ms, and convolution-requantization 2,080.030 ms. These counters overlap and are not exclusive phases.

The four phase tick counts sum to 2,165,877,074 ticks, 879 ticks (0.00264 ms) below the recorded total; treat this as close agreement at the available counter precision, not an exact boundary proof. The distinct node groups sum to 6,333.525 ms, about 12.053 ms below the graph phase, consistent with graph overhead outside node intervals. The profile declares the additional pack/transfer/DMA/parse/requant counters nested, so those counters cannot be added to each other or to phase/operator totals. Host-observed 7.0462 s is also a separate scope. One frame gives no P50/P95 or sustained throughput.

## Proposed experiment (not run)

Test moving the three profiled maxpool nodes (70, 71, 72) to the PL data path as one candidate. Their recorded PS interval is 131.042 ms, which is an optimistic maximum saving before any added transfers; real end-to-end gain could be smaller or negative.

Keep the frozen model, fixed input, bitstream, clock and warm-up policy constant. Collect at least 30 full-frame baseline and 30 candidate runs. For every run, capture end-to-end and phase times, counter boundaries, DMA byte/call counts, and the logical output hash. Report P50/P95 and continuous throughput only from repeated runs. Proposed acceptance: exact logical output parity and at least 1% improvement in transfer-inclusive median latency against the repeated baseline. Check implementation resource and timing reports before a board trial. This is an experiment plan, not a claim that the optimization has been implemented or passed.

## Limits

- One frame only; no throughput distribution or FPS conclusion.
- Nested counter values cannot be summed as exclusive wall time.
- The ELF, input image, expected output bytes, diagnostic binary, bitstream timing report, and resource report are not attached; their referenced hashes were not independently checked.
- No independent timer calibration, PL busy utilization, memory-port utilization, or frequency closure evidence is provided.

## Skills and operation log

Loaded zynq-ps-pl-performance version 1.0.0-rc1 and its references/workflow.md. Read the task and two case inputs. Used standard-library JSON parsing and arithmetic. No board, network, training, weight-loading, or model-selection action was taken. Reports were written only inside the assigned output directory.