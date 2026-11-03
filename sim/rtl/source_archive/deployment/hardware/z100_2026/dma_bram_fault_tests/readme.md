# 错误、流中断和重复恢复下的 BRAM 观测

> 历史实验归档（说明更新：2026-11-03）。本目录保存早期组件试验的条件和边界，不是最新 12 路/ACP 整机的操作入口，也不代表本次重新执行。旧 `tools/validate_z100_*.py`、绝对工程路径和盘符映射依赖原完整实验环境，本复现包不提供这些归档套件的独立可执行闭包。

当前可迁移检查入口为在**本包根目录**执行 `python -B sim/run_rtl.py --check`，详见 [当前 RTL 说明](../../../../../readme.md) 和 [九项回归范围](../../../../../reproduction.md)。当前九项 runner **不执行本目录的历史 DMA/候选试验**，其输入检查通过也不能更新本目录历史结论。

本阶段复用上一阶段已通过正向自检的被动观察器及 bind，二者未修改。`tb_z100_dma_bram_fault.sv` 从历史 `dma_retry_tests/tb_z100_dma_retry.sv` 复制，仅改模块名；故障注入、超时窗口、AXI/AXIS 稳定性、旧缓冲保护、复位边界及重载整数结果断言保持原样。

历史 runner `validate_z100_bram_faults.py` 记录的场景为：

| 场景 | 实际测试条件 |
|---|---|
| read_slverr | 80 拍读 SLVERR，经 HP0/DMA 握手，TX 错误掩码 0x20 |
| read_decerr | 80 拍读 DECERR，经 HP0/DMA 握手，TX 错误掩码 0x40 |
| bresp | 一次实际写响应 SLVERR，经 HP0/DMA 握手，RX 错误掩码 0x20 |
| mm2s_abort | 80 拍输入中的前 2 拍已被 DMA/核心接收，TLAST 前中断 |
| s2mm_abort | 5 拍响应中的前 2 拍已被核心/DMA接收，TLAST 前中断 |
| repeated_error | 两次各 4/80 拍 SLVERR 后暂停，64 次轮询仍无 TX 错误位，由测试台超时触发恢复；错误跨 reset 保留，期间分别 PROBE，最后显式撤去外部错误再重载 |
| permanent_read | 保持真实 slice/HP0 RVALID 停顿；200 次测试台轮询后仍 reset pending、ABORT 保持、不释放、不重载 |
| permanent_write | 已接受 AW、WVALID 停顿；200 次测试台轮询后仍 reset pending、ABORT 保持、不释放、不重载 |

每例重新编译实际 IP、记录输入/快照/工具命令和日志哈希，并要求两个准确 XPM 存储路径的观察结果。正向恢复例要求两处读写计数均非零；永久停顿例允许某 FIFO 没有访问，因为阻止新流量正是负向预期。负向例的有效性来自实际停顿、reset pending 和 ABORT 观测，不将零访问写成非零碰撞覆盖。

观察器保持原边界：前 64 个全局初始化时钟沿不检查，单列其已知写入数并要求为零；此后的 reset 不屏蔽碰撞检查。读写次数是内部 RAM 事件，不能当成 AXI 有效负载拍数。并发和全部 128 地址回卷覆盖见此前八轮阶段，不要求每个故障例重复该覆盖。

HP0 和 AXI-Lite 编程是测试台行为模型，未执行生产 ARM C，也不是 PS7/真实 DDR。200/64 次轮询只是测试台窗口，不是生产超时时间。有限 RTL 观测不关闭 REQP-181、LUTAR-1 或 RTSTAT-10，也不代替时序网表、实板和缓存一致性验收。
