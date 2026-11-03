# Z100 interrupted error and retry tests

> 历史实验归档（说明更新：2026-11-03）。本目录保存早期组件试验的条件和边界，不是最新 12 路/ACP 整机的操作入口，也不代表本次重新执行。旧 `tools/validate_z100_*.py`、绝对工程路径和盘符映射依赖原完整实验环境，本复现包不提供这些归档套件的独立可执行闭包。

当前可迁移检查入口为在**本包根目录**执行 `python -B sim/run_rtl.py --check`，详见 [当前 RTL 说明](../../../../../readme.md) 和 [九项回归范围](../../../../../reproduction.md)。当前九项 runner **不执行本目录的历史 DMA/候选试验**，其输入检查通过也不能更新本目录历史结论。

This independent actual-IP harness preserves the accepted read-side TB. It instantiates the generated AMD DMA, response slice, protocol converters, crossbar and accelerator. CPU AXI-Lite and HP0 memory remain behavioral models; it does not execute production C or PS7.

Historical stages: `retry_early_error`, `retry_repeated_error`, `retry_permanent_read`. The former task-owned `X:` mapping is not part of the current package:

旧场景标识见下文；重跑这些归档场景需另行恢复并核对原实际 IP 导出、runner 和工具环境。

`retry_early_error` accepts exactly four real SLVERR beats at HP0 and DMA in an unfinished 80-beat LOAD, before RLAST/TLAST. The HP0 model then delays generation of subsequent beats without retracting an existing VALID. Up to 64 testbench TX SR polls observe whether the error is visible. An observed error or the bounded poll timeout triggers ABORT and DMA-only reset. The log distinguishes these triggers; successful recovery must not be described as proof of an early DMA status indication. The configured C recovery budget and five-second transfer deadline are not executed by this SV fixture.

The finite read pause opens forty clocks after reset programming while status polling runs. SLVERR injection remains enabled through reset and the following PROBE. All accepted old reads must close at the status and ABORT-clear boundaries before buffer release. Only after recovery is the modeled memory fault disabled for a healthy PROBE/LOAD/RUN.

`retry_repeated_error` repeats this failure/recovery/PROBE sequence twice on distinct TX/RX addresses. Error injection is never disabled between the two failures or resets. After each release, both old buffers are continuously monitored: RX has five sentinel words; TX has 80 poisoned words and an accepted-address reuse guard. Both released buffer pairs stay guarded during the second episode and final healthy reload from a third TX copy. This covers two controlled errors across resets, not an unbounded retry policy implemented in firmware.

`retry_permanent_read` holds the response-slice return gate closed after genuine HP0 and actual-slice RVALID backpressure. It polls DMA reset for a bounded 200 iterations without opening the gate. A passing negative result requires reset pending, external data pending and ABORT held, with no release/reload. If internal reset completion occurs while external data remains pending, the case explicitly fails and requests escalation; it does not silently add a firmware outstanding-counter feature.

All actual AXI payload stability checks are retained; the real response slice and HP0 endpoint are never externally reset during DMA-only recovery. DMA AXIS cancellation is allowed only during the DMA's own reset window. External pending checks are verification oracles. Firmware `faulted`, `active`, buffer ownership and new-request lockout are verified separately by production-C host mocks, not by this RTL BFM.

Reports, raw tool logs, source snapshots and input manifests are unique under `validation/board_z100/dma_retry_tests/`; builds are under `deployment/build/z100_dma_retry_tests/`. Final stage acceptance requires common TB/runner identities and an unchanged historical normal-stage compatibility run.
