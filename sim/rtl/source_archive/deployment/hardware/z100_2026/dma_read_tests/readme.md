# Z100 read-side fault tests

> 历史实验归档（说明更新：2026-11-03）。本目录保存早期组件试验的条件和边界，不是最新 12 路/ACP 整机的操作入口，也不代表本次重新执行。旧 `tools/validate_z100_*.py`、绝对工程路径和盘符映射依赖原完整实验环境，本复现包不提供这些归档套件的独立可执行闭包。

当前可迁移检查入口为在**本包根目录**执行 `python -B sim/run_rtl.py --check`，详见 [当前 RTL 说明](../../../../../readme.md) 和 [九项回归范围](../../../../../reproduction.md)。当前九项 runner **不执行本目录的历史 DMA/候选试验**，其输入检查通过也不能更新本目录历史结论。

This isolated testbench uses the same actual generated AMD DMA, response slice, protocol converters, crossbar and accelerator as the accepted fault tests. CPU AXI-Lite and HP0 memory are behavioral models. It does not execute production C, PS7 or physical DDR.

The original run used an external interpreter and task-owned `X:` export mapping; those paths are not current runnable instructions:

旧场景标识见下文；重跑这些归档场景需另行恢复并核对原实际 IP 导出、runner 和工具环境。

- `read_mm2s_abort`: the real DMA and core accept two of the 80 LOAD input beats, without TLAST. A paired TVALID/TREADY gate then stops acceptance; ABORT and DMA-only reset interrupt the operation. DMA AXIS payload stability remains strict outside its own reset window. ABORT alone does not exempt the DMA source from stability checks.
- `read_rbackpressure`: a paired RVALID/RREADY gate at the actual response-slice output stops read returns before the DMA. The case requires a real slice RVALID/RREADY stall and propagated HP0 RVALID/RREADY stall for at least ten cycles. Both payloads remain subject to strict stability assertions, including during DMA reset, because neither source is externally reset.
- `read_slverr` and `read_decerr`: HP0 generates error responses. The case requires actual HP0 and DMA error handshakes, the precise RRESP code at both boundaries, and the corresponding TX SR bit (0x20 or 0x40). The injection is finite and is disabled forty clocks after reset programming; this is not proof for perpetual or repeated errors.

All cases use the firmware-style register sequence, concurrently release test-only holds after forty clocks, and check accepted read/write accounting at the status fence and actual ABORT-clear write. Old stream and slice VALID must be clear. These external-queue tests are acceptance oracles, not outstanding counters implemented in production firmware. Failure stops the test and never becomes a later PASS.

After successful recovery, the old TX source is poisoned and old RX is protected by a continuously checked sentinel. A distinct TX copy is used for full PROBE/LOAD/RUN with fresh sequences, buffer guards and signed integer reference results. Reset does not roll back already committed writes.

Unique logs, input manifests, source snapshots and run reports go under `validation/board_z100/dma_read_tests/`; builds go under `deployment/build/z100_dma_read_tests/`. Four accepted runs must share the final testbench and runner identities. The unchanged original normal stage is also rerun for runner compatibility.

Permanent read stalls, sustained/repeated response errors, arbitrary reset phases, larger burst/page/order cases, multi-outstanding HP0 behavior, BRAM collision and physical board operation remain separate work.
