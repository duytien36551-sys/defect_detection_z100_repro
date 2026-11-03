# Registered response-bank selection candidate, V1

> 历史实验归档（说明更新：2026-11-03）。本目录保存早期组件试验的条件和边界，不是最新 12 路/ACP 整机的操作入口，也不代表本次重新执行。旧 `tools/validate_z100_*.py`、绝对工程路径和盘符映射依赖原完整实验环境，本复现包不提供这些归档套件的独立可执行闭包。

当前可迁移检查入口为在**本包根目录**执行 `python -B sim/run_rtl.py --check`，详见 [当前 RTL 说明](../../../../../readme.md) 和 [九项回归范围](../../../../../reproduction.md)。当前九项 runner **不执行本目录的历史 DMA/候选试验**，其输入检查通过也不能更新本目录历史结论。

## 历史候选范围

这是旧 V12 的 28 源码、2016 DSP 候选，不是当前 S12/1252 DSP 最终方案；不能从本归档推断该候选已被采用或获得性能提升。文中来源路径属于历史证据定位，未随包交付的记录不作为当前已通过结果。

## Scope

This candidate is a one-expression, valid-domain-equivalent experiment on the frozen 28-source V12 core. It does not change request admission, load/conflict behavior, push/pop ownership, capacity, datapath latency, site count, or the 2016-DSP mapping target. The frozen A sources and all prior reports remain unchanged.

The only RTL difference from `build/v12p_d46da432/rtl/z100_feature_banks_pingpong_writepipe_v7.sv` is:

```diff
- wire response_bank=read_pending ? response_bank_q : req_bank;
+ wire response_bank=response_bank_q;
```

`out_valid` is qualified by `read_pending`, and `response_bank_q` is captured on the request handshake that opens the pending response. Therefore the selected bank is identical whenever the output is valid. When `read_pending` is false, output payload is outside the valid/ready transaction contract and may differ. Tests must keep exact valid sequence, valid payload, ready/control behavior, and valid-stall stability; they may ignore payload only while `out_valid == 0`.

## Evidence and limits

- Frozen source SHA-256: `70719780ff5428755dc562684fedd9c793a9375eeebd93959df11aafb9232662`.
- Candidate SHA-256: `fd90b026c3992b49819ead401e705eda599a8b3528547fba00da34dafbff5c04`.
- A primary-owned exhaustive 2-state equation check is recorded at `validation/board_z100/response_bank_primary_boolean_review/20261027T133834.407679Z/result.json`, checker SHA-256 `f3cae2b8fce1fc0a9d638fdf41a6969f516cb2fa48dc0131675bb84ce1b95574`. It covered 256 Boolean combinations (32 valid cases; 64 differing selections only while invalid). This is not RTL formal, XSim, memory, timing, route, or performance evidence.
- `tb_z100_registered_response_bank_miter_v1.sv` is the directed RTL old-vs-new bank-module miter. It compares exact control and valid behavior, valid payload, and stalled payload stability. Invalid-cycle payload is intentionally excluded from equivalence.
- The versioned runner then stages the original V12 Conv/Pool/retained-Conv golden test, substitutes only this bank RTL, and requires all seven frozen marker lines exactly. Any count or marker mismatch fails closed.
- The conditional implementation runner rebuilds all 28 original A sources from fresh RTL, replacing only this bank module. It does not reuse a pre-candidate DCP. It uses `xc7z100ffg900-2`, `row_clk=10 ns`, synthesis at 2 threads and implementation at 8 threads, default placement/setup physical optimization, the existing `-hold_fix`, and Default routing. No Pblock, false path, multicycle, timing relaxation, staged packer, or raw-buffer candidate is applied.

The historical queue policy required phase 1 completion and the primary independent review; it is recorded here for provenance and is not a pending job or authorization to run tools. Phase 1 must have a fully legal route and timing must remain failed before simulations and a new implementation are admitted. A phase-1 timing pass skips physical implementation and preserves this candidate for later review. Any phase-1 error or failed review closes the queue without launching candidate simulations or implementation.

No full platform, board, model-quality, or 30-FPS acceptance is implied by these component and core-only checks.
