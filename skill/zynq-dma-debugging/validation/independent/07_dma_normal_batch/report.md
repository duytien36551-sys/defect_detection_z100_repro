# Independent review: 07_dma_normal_batch

## Scope

Read only this case's task and inputs, plus the required zynq-dma-debugging skill.md and references/workflow.md. No board command, reset, or repeated request was made.

## Run identity and timeline

The acceptance record reports dry_run=false, status complete, case parity and batch acceptance true, 20/20 round trips completed, and no first error. Model SHA-256 f5394b31cf55502d6b3bc458b212db2c3422f8fe30dbdb509742f5c085a8d9b3 matches its declared baseline SHA. Protocol is joint18-v8/1; classes hash is 5f6b28fea47fae5e78e5ab783049d5eb2c5b3a03ac255b94eb10ec95866807b1. The identity probe says input rgb-u8-416-letterbox114, local 192.168.10.1:55901 to peer 192.168.10.2:5001, interface index 23.

| Event | UTC |
|---|---|
| Batch started | 2026-10-15 19:15:59.749551 |
| Identity probe | 2026-10-15 19:15:59.805269 |
| First request started | 2026-10-15 19:15:59.807276 |
| Last request finished | 2026-10-15 19:17:07.597458 |
| Batch finished | 2026-10-15 19:17:07.604033 |

## Request outcomes and timing

All 20 requests in requests.jsonl equal the acceptance request entries; the log's embedded JSON also matches the acceptance record. Ten PCB requests use one repeated image/tensor hash pair and class id 3 PCB_OP; ten pin requests use another repeated pair and class id 9 PIN_破损. Thus the batch contains two unique inputs repeated ten times each, not 20 independent images. Every expected/actual comparison passes: one expected and one actual row, same class/name, score error zero, coordinate error zero.

The per-request elapsed_seconds median is 3.3825 s (the summary rounds to 3.383 s), with range 3.359–3.406 s and sum 67.671 s. Timestamp-derived request durations have median 3.3867 s and range 3.3630–3.3992 s. Batch start-to-finish timestamp duration is 67.8545 s (reported as 67.86 s); first request start to last request finish spans 67.7902 s. These values differ, and their timer boundaries are not explained. Keep them as separate timing evidence. No P95 is supplied.

## Contract discrepancy and recovery gap

Metadata says box_space=normalized-model-xyxy, while the example coordinates include [112.27, 108.61, 123.00, 119.00] and [17.21, 143.34, 35.18, 211.41], which are greater than 1. Expected/actual equality is verified from the records, but the declared coordinate semantics are unresolved.

The acceptance record explicitly says cold boot and DMA recovery are separate acceptance stages. This case includes no failed request, DMA register/descriptor snapshot, TLAST record, buffer ownership event, cache attribute, or cache synchronization implementation. Therefore it provides no recovery or fault-root-cause evidence.

## Safe read-only next check (proposal)

Review the already-saved host-side run artifacts and matching driver implementation for coordinate scaling, buffer ownership, and cache synchronization. If an earlier failed-run snapshot exists, inspect its saved transaction sequence and DMA status without issuing commands to the board. Those additional artifacts were not supplied or inspected here.

## Limits

- The 20 observations repeat two inputs; they do not establish general workload latency.
- Timing fields use different boundaries; P95 is not supplied.
- Success on this initialized batch does not prove cold-boot or DMA failure recovery.
- Do not infer cache failure from absent flush calls without checking the actual driver behavior.

## Skills and operation log

Loaded zynq-dma-debugging version 1.0.0-rc1 and its references/workflow.md. Parsed only the task and three case inputs with standard-library JSON/JSONL parsing, timestamp arithmetic and SHA-256. No hardware, network, training, or process action was taken. Reports were written only in the assigned output directory.