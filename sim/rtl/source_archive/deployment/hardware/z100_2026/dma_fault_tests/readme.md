# Z100 DMA fault simulation

> 历史实验归档（说明更新：2026-11-03）。本目录保存早期组件试验的条件和边界，不是最新 12 路/ACP 整机的操作入口，也不代表本次重新执行。旧 `tools/validate_z100_*.py`、绝对工程路径和盘符映射依赖原完整实验环境，本复现包不提供这些归档套件的独立可执行闭包。

当前可迁移检查入口为在**本包根目录**执行 `python -B sim/run_rtl.py --check`，详见 [当前 RTL 说明](../../../../../readme.md) 和 [九项回归范围](../../../../../reproduction.md)。当前九项 runner **不执行本目录的历史 DMA/候选试验**，其输入检查通过也不能更新本目录历史结论。

This offline testbench instantiates the exported AMD AXI DMA, generated AXI4-to-AXI3 converters, `mem_xbar`, the public MM2S response slice, and the tile64 accelerator. Its CPU AXI-Lite master and HP0 AXI3 DDR endpoint are behavioral testbench models. The testbench does not instantiate PS7 or model physical DDR electrical/timing behavior, and it does not execute the production C driver.

The archived stages are listed below; their original isolated XSim environment is not a current package command:

旧场景标识见下文；重跑这些归档场景需另行恢复并核对原实际 IP 导出、runner 和工具环境。

Each runner invocation creates unique build and evidence directories under `deployment/build/z100_dma_fault_tests/<run-id>` and `validation/board_z100/dma_fault_tests/<run-id>`. The JSON report records the exact runner arguments, runner and testbench hashes, source hashes before and after, each tool command, return code, timeout status, log hash, coverage lines, and unresolved coverage.

The stages cover different boundaries:

- `fault_partial_w` receives a real HP0 AW for five beats, accepts exactly two HP0 W beats, then holds WREADY for 40 cycles while DMA reset polling runs. It records AW/W/B counts at the ResetIsDone and ABORT-release boundaries, then checks a fresh PROBE/LOAD/RUN and guards.
- `fault_tlast_abort` gates both TVALID into the DMA and TREADY back to the core after exactly two of five real S2MM response handshakes. It confirms TLAST is still zero, the core has not finished, and the third source beat is held stable before confirmed ABORT. The core's withdrawal of that pending beat after ABORT is logged as cancellation. The test-only gate opens after 40 cycles while reset polling continues. This covers the accelerator-to-DMA S2MM response stream only; it does not cover MM2S input-stream truncation.
- `fault_persistent` holds HP0 WREADY low after a real AW and WVALID. A bounded 200-iteration testbench poll records whether the DMA reset bits remain set. A passing negative result leaves ABORT asserted and does not release or reuse the buffer. This window is distinct from the firmware's 5-second transfer deadline and its default 10,000,000 `recover()` poll budget (or configured `timeout_polls`). The testbench does not model the C `faulted`, `active`, or `ready()` fields.
- `fault_bresp` injects one SLVERR on a real HP0 B response and records the BRESP=2 handshake at both HP0 and DMA, plus the pre-reset S2MM error status. It then verifies DMA-only reset, closed bus accounting, old-buffer guards, and fresh PROBE/LOAD/RUN.

The normal `reset_dma_only` testbench task mirrors the production register order but adds a fail-closed verification gate: it permits the modeled control=0 write only when the sampled DMA and HP0 AXI/AXIS counters are closed. That gate is a testbench acceptance oracle; production `recover()` does not inspect those counters. The separate host-mock firmware tests are needed to cover production C state transitions.

The fault stages do not cover RVALID held while RREADY is low, MM2S RRESP errors, multiple outstanding transactions or out-of-order responses, XPM FIFO same-address collisions, physical DDR behavior, or execution on hardware.
