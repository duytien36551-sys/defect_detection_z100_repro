# 硬件源码与已有综合实现结果

本包提供53份RTL/ROM、Zynq PS的BD/Tcl、约束和源码构建入口，不依赖旧DCP。此摘要整理已有结果，本次收尾没有启动Vivado。

## 原最终平台历史结果

以下数值来自原最终平台的历史综合与实现报告，对应`board/artifacts/z100_platform.bit`和`.xsa`；原报告身份见`final_hardware/synthesis_implementation_summary.json`。

| 资源 | 综合使用量 | 最终实现使用量 | 最终实现占比 |
| --- | ---: | ---: | ---: |
| LUT | 102815 | 95260 | 34.34% |
| 寄存器 | 98746 | 98764 | 17.8% |
| BRAM Tile | 287.5 | 287.5 | 38.08% |
| DSP | 1252 | 1252 | 61.98% |

历史最终WNS/TNS为0.005/0.0ns，WHS/THS为0.045/0.0ns；脉宽最差裕量4.232ns。可布线网络238792条，完全布通238792条，路由错误0。DRC Error/Critical Warning计数0，Warning分组1447，不能描述为零警告。

## 额外源码构建的状态

此前的源码构建已完成综合和布局；布局WNS为0.341ns、WHS为-0.239ns，这些是布局阶段数值。用户随后要求停止额外验证，构建在布线阶段停止，未形成最终时序验收、bit或XSA导出结果。停止状态不是时序通过或失败结论，也不影响所附源码、脚本与原最终上板文件的交付。

## 赛方使用入口

在包根目录执行`build/rebuild_hardware_source.py`，完整环境和命令见根`readme.md`及`build/hardware_source/readme.md`。复现者自行安装Vivado2026.1，选择包外短输出路径。新生成的对象、DCP、原始rpt和日志均留在包外；本包保留原最终文件及报告摘要。新产物仍需按实际运行结果判断。
