# Z100 burst and 4KiB boundary simulation

> 历史实验归档（说明更新：2026-11-03）。本目录保存早期组件试验的条件和边界，不是最新 12 路/ACP 整机的操作入口，也不代表本次重新执行。旧 `tools/validate_z100_*.py`、绝对工程路径和盘符映射依赖原完整实验环境，本复现包不提供这些归档套件的独立可执行闭包。

当前可迁移检查入口为在**本包根目录**执行 `python -B sim/run_rtl.py --check`，详见 [当前 RTL 说明](../../../../../readme.md) 和 [九项回归范围](../../../../../reproduction.md)。当前九项 runner **不执行本目录的历史 DMA/候选试验**，其输入检查通过也不能更新本目录历史结论。

The pinned DMA is 32-bit, simple mode, DRE disabled, with a maximum 16-beat burst on each memory channel. Buffers remain 64-byte aligned. No production hardware or firmware is changed.

旧场景标识见下文；重跑这些归档场景需另行恢复并核对原实际 IP 导出、runner 和工具环境。

The old runner used a task-owned `X:` mapping (not required or created by the current package). Historical evidence/build directories were under `validation/board_z100/dma_page_tests/` and `deployment/build/z100_dma_page_tests/`.

The test uses actual AMD DMA, response slice, converters, crossbar and accelerator. CPU AXI-Lite and HP0 memory remain behavioral. The HP0 model accepts only one read and one write outstanding; this does not test out-of-order completions or multiple independent IDs.

All accepted AR/AW requests at DMA and HP0 are checked for word alignment, 32-bit size, 1–16 beats and containment in one 4KiB page. Address/length and RLAST/WLAST handshake histories are recorded independently. Region scoreboards check exact contiguous address coverage and every LAST position after a transfer, allowing legal AW/W timing skew.

- Normal: an 80-word LOAD starts at 0x0FC0, crossing 0x1000. A 32-word RUN input starts at 0x2FC0 and its 37-word response starts at 0x5FC0, crossing 0x3000/0x6000. All 32 signed results are compared with bias 7 plus weight 3 times deterministic activations. Both response guards and input guards are checked.
- Read reset: the first-page read completes (16 beats and RLAST), then the actual HP0 accepts the 0x1000 AR. The endpoint holds generation of its data. DMA-only reset releases the finite hold after 40 clocks while polling, and must close all accepted reads before releasing buffers.
- Write reset: a normal LOAD precedes the old RUN. The first 16-beat output burst and its B response complete; the next page at 0x6000 accepts two W beats before stalling. Reset must close every accepted transaction. The interrupted original response is discarded, not treated as a valid inference result or rolled back.

Recovery cases guard the entire old TX and RX region, including all 37 response words when applicable, continuously check later memory contents, and reject a new accepted read burst that overlaps poisoned TX. A distinct TX copy is used for new-sequence PROBE/LOAD/RUN after the original software-style status and ABORT-clear boundaries.

All memory AXI stability assertions remain strict during DMA-only reset. External pending checks are verification oracles, not additional production-C hardware queries. Source snapshots, tool results and logs are retained; final evidence must use one frozen TB/runner and include the original normal entry regression. No PS7 execution, physical DDR timing, arbitrary transfer size/address, universal ordering or FPS acceptance is implied.
