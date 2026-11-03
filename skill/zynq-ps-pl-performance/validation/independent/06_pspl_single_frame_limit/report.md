# Single-frame performance evidence — 06_pspl_single_frame_limit

## Conclusion

The inputs support one unprofiled one-shot frame and one profiled one-shot timing summary. They do **not** support P50/P95, sustained FPS, a speedup claim, pure PL busy time, or full end-to-end transport. The board record itself says accuracy, FPS and release were not accepted. No hardware was operated for this review.

## Reportable timing

Profile summary uses 333333343 Hz (generated CPU clock/2 from matched BSP; oscillator not independently measured).

| Phase | ms |
|---|---:|
| preprocess | 27.571 |
| graph | 6345.578 |
| dequantization | 16.228 |
| decode | 108.254 |

The separate first-frame baseline summary reports total **6579.095 ms**, comprising preprocess 27.659, graph 6403.554, dequantization 16.235, and decode 131.643 ms. Its largest listed node is convolution node 0 at 497.216 ms. The board-result total counter converts to 6579.095 ms at the supplied profile timer rate.

Profiler records 6413 DMA calls; TX 82,883,776 B; RX 57,057,860 B; 94 loads and 6319 runs. These are counter totals, not an isolated bandwidth measurement. Load/run, transfer, DMA prepare/poll/finalize, parsing and conv/requant counters are nested or overlapping; DMA poll includes CPU overhead. Do not add them as independent phase times or call them PL time.

One baseline total is 6579.095 ms and one profiled total is 6497.634 ms; reported one-sample difference is -1.238%. The record explicitly says one run each and cache/sampling variability prevent measuring instrumentation overhead or claiming speedup. Recalculation gives -1.238%, still only an observed pair difference.

## Scope, identity and unsupported metrics

- Reported phases are within one full-model inference result. The profile states full-pipeline transport was not measured; no sustained FPS was measured. One sample each gives no usable latency distribution/P95.
- Board result is one fixed validation image, 640 input, 613,200 logical head bytes, 0 reported mismatches and 2 detections. It reports a provisional baseline INT8 package and ELF SHA `9f326aa8d74c47fc0dca860d359de1a5e37997ebf686c5d3dc1507cbc0ffb3df`. The raw head bytes are not included, so parity could not be independently rerun.
- Profile summary references a historical `result.json` SHA `dfb56c4ea355983dde9e18996db37b24fddc177a55d2a4d2851577eaa1677a74`; the provided `board_result.json` SHA is `5b134868fc2c79fec89d635addcdb8677d1d9f03c0619f0743720546a774cd8c` and differs. The historical file is absent. Its first-frame-summary input hash does match the supplied file. Profile run ELF/bitstream identity is otherwise missing, so the two summaries are not conclusively bound to the same exact firmware.
- `release_eligible=false`, `accuracy_accepted=false`, `fps_accepted=false`. No routed timing/resource report or board frequency measurement is supplied.

## Minimum follow-up collection

With separate board authorization and exact board/model/ELF/bitstream/input identity fixed, capture a warm-up and at least 100 consecutive complete requests. For each request, retain unrounded monotonic times at outer application entry/return and phase boundaries (preprocess, pack, DMA prepare/wait/finalize, graph/PL, decode, response), actual TX/RX bytes, completion/error and sequence ID. Add an unprofiled control block of the same inputs to bound instrumentation overhead. Report raw sample count and percentile convention, P50/P95, and completed frames divided by measured wall time for sustained throughput.

Next candidate experiment, only if the repeated profile still confirms compute dominance: a narrowly scoped node-0 convolution/packing variant. Keep model, input and board fixed; require logical output parity and paired repeated latency distributions whose improvement exceeds run-to-run variability. This is a proposed experiment, not a measured gain.

