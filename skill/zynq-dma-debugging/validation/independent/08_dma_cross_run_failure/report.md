# DMA chronology and evidence — 08_dma_cross_run_failure

## Conclusion

A PCB request failure is observed. The separate 20-request diagnostic passed, but timestamps place it **before** the failure despite its “later” filename. It is not recovery evidence. The post-failure register snapshot does not establish the root cause. No board operation was performed in this review.

## Runs in timestamp order (UTC)

| Order | Record | Observation |
|---|---|---|
| 1 | Diagnostic 2026-10-15T18:41:21.113766+00:00–2026-10-15T18:42:28.899138+00:00 | 20/20 pass (10 PCB, 10 PIN); comparisons pass. |
| 2 | Failed retest 2026-10-15T18:44:38.001238+00:00–2026-10-15T18:44:39.902043+00:00 | One PCB error; 1/2 completed; 20-roundtrip minimum not met. |
| 3 | Snapshot 2026-10-15T18:45:03.060841+00:00 (complete 2026-10-15T18:45:05.111888+00:00) | Post-failure capture; ELF matches failed build report. |

The diagnostic ended 129.102s before the failed run began. Both runs report the same model SHA `f5394b31cf55502d6b3bc458b212db2c3422f8fe30dbdb509742f5c085a8d9b3`, class SHA `5f6b28fea47fae5e78e5ab783049d5eb2c5b3a03ac255b94eb10ec95866807b1`, protocol `joint18-v8/1`, and input `rgb-u8-416-letterbox114`. Diagnostic ELF/XSA/bitstream/run-session identity is absent; its path and local port differ. Do not merge these records.

## Direct failure and snapshot observations

- Sequence 1 PCB request returned `BoardProtocolError: board rejected inference: board inference failed` after 1.844s; actual rows/comparison are null. Acceptance flags parity/batch false; no successful-request latency distribution exists.
- Failed build ELF SHA and post-failure manifest ELF SHA match: `2655c9fdbad33ac948c0c404117cc7d6210a38b56061d863e57b4d466a603e6b`. Build report says physical DMA width was not verified.
- The 92-byte register block was manually decoded as little-endian u32 using manifest offsets: MM2S length offset 40=`0x000007c0` (1,984 B); S2MM length offset 88=`0x00000014` (20 B); MM2S status offset 4=`0x00001002`; S2MM status offset 52=`0x00001001`. Snapshot manifest declares PL R0-R3 values `0x00000002`, `0x0010001b`, `0x00000001`, `0x00000001`; the separate 16-byte PL register file it references is absent, so those values were not independently checked. The AXI words above are post-failure values; no status contract or TLAST waveform is supplied.
- Snapshot was generated 23.159s after the failed record ended. Manifest says RX buffer includes prior-response bytes. A 20-byte RX could be an error reply or a short/incomplete transfer; neither is proven.
- XSCT log reports host access initial `0` and restored `1`, conflicting with manifest save/restore/verify policy. It logs CPU Running → Stopped → resumed; this is historical fixture evidence, not an action here. Reconcile before relying on capture procedure.

## Hypotheses and next check

Transfer/response-stage trouble is plausible, not proven. Unresolved: TLAST/length mismatch, accelerator exception, cache maintenance, ownership/race, initialization, or response decode. There is no same-run transaction trace, accepted stream-byte count, cache attribute/sync evidence, or decoded error code. The manifest-referenced raw PL register file is absent; driver/context binary structures are undocumented here and were not guessed.

At a separately authorized safe reproduction with exact failed ELF/XSA/model/input identity, capture one sequence-correlated trace of register writes/status, MM2S/S2MM actual bytes, accepted AXI-stream beats/TLAST, raw response/error, buffer ownership and cache sync extents. Valid framing plus explicit error points above transport; framing/length/status mismatch points into DMA/stream handling. Preserve first failure; do not reset, replay or reuse buffers until channel state and ownership are known under the board contract.

See `report.json` for evidence pointers, lines and byte offsets.
