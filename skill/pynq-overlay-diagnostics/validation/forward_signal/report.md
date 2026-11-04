# 信号采集离线前向测试

检查日期：2026-11-03；环境：Windows，Python 3.12.12；技能版本：1.0.0。目标器件为 7z020；实际板卡型号和 PYNQ 版本未知。

## 输入与文件

| 文件 | 用途 | SHA-256 |
| --- | --- | --- |
| `.codex/pynq_general_20261103/draft/pynq-overlay-diagnostics/examples/metadata_7020/design_excerpt.hwh` | 输入 HWH，2,803 字节 | `a19ef679ab6d34b5f69d248c2169a3b95c946d8f920ea164f34589d34d54c1ee` |
| `.codex/pynq_general_20261103/forward_signal/contract.json` | 本次新建的传输契约 | `aae88511594f5fbd57e4aea40f2efc1939282f289d4caf08f3f1a1a25f7fff7d` |
| `.codex/pynq_general_20261103/draft/pynq-overlay-diagnostics/scripts/audit_overlay.py` | 实际执行的审计脚本 | `f3039b073ee65e42ab268e327c09fa70375b53d93b13c19bc09634f1a406b069` |
| `.codex/pynq_general_20261103/forward_signal/audit.json` | 本次审计输出 | `b5df985862ae030e2f1ea44ec572605ebd43ef03447cf12804f679b140693c67` |
| `.codex/pynq_general_20261103/draft/pynq-overlay-diagnostics/SKILL.md` | 执行说明 | `47e1c9753fd3fd194e09984aa9e60c9be6e182445ebedb6f00eb6112d42ffb64` |
| `.codex/pynq_general_20261103/draft/pynq-overlay-diagnostics/references/contracts.md` | 配置和状态契约 | `8c7120f8630a3a03ccb3effac01c0132eb566183c0c48b7d41c8b1c08b699e93` |
| `.codex/pynq_general_20261103/draft/pynq-overlay-diagnostics/assets/report_template.md` | 报告模板 | `186264ac395984074019d93b4943a3427318b3aef4202886fa457e1b760062cd` |

未提供 BIT，BIT/HWH 同构建关系未检查。HWH 是最小参数摘录，不是可加载 Overlay。

## 结果

状态：`INCOMPLETE`；审计进程退出码：`4`；`hardware_execution=false`。

HWH 声明器件 `7z020` 和 `/axi_dma_0` (`xilinx.com:ip:axi_dma:7.1`)，与契约相符。DMA 为 simple mode、非 micro DMA，长度字段宽度 16 位，单次上限 65,535 字节；MM2S 和 S2MM 均启用，memory-map 宽度均为 32 位，DRE 均关闭。

| 方向 | 契约 shape / dtype | 传输字节数 / 缓冲容量 | 静态检查 |
| --- | --- | --- | --- |
| MM2S | `[4096]` / `float32` | 16,384 / 16,384 | 容量和 DMA 长度通过；无物理地址，4 字节对齐未知 |
| S2MM | `[2048]` / `float32` | 8,192 / 8,192 | 容量和 DMA 长度通过；无物理地址，4 字节对齐未知 |

`INCOMPLETE` 来自未提供 BIT 和未观察到两个缓冲区的物理地址，不是检测到的器件、IP、容量或 DMA 长度冲突。

## 可复现命令

```powershell
python -B 'SKILL_ROOT\scripts\audit_overlay.py' --hwh 'SKILL_ROOT\examples\metadata_7020\design_excerpt.hwh' --config 'VALIDATION_WORKSPACE\forward_signal\contract.json' --out 'VALIDATION_WORKSPACE\forward_signal\audit.json'
```

实际退出码：`4`。

## 限制与下一步

本次只检查静态元数据和传输契约，未访问板卡、加载 Overlay、执行 DMA 或运行 notebook。未验证 TLAST/TKEEP、缓存一致性、缓冲区所有权、数据正确性或计时；不构成硬件验收。

下一步是在目标 PYNQ 板上确认实际板卡与 PYNQ 版本，取得同一构建的 BIT/HWH 及构建清单；记录实际分配的 MM2S/S2MM 物理地址并确认 4 字节对齐；再按真实流协议检查 TLAST/TKEEP、缓存/所有权和输出参考结果。
