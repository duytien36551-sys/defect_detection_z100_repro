# RTL仿真源码与运行入口

本目录保留源工程测试台、当前ACP核心回归源文件、include及所需ROM/输入/期望值。静态源码索引见`source_inventory.json`；推荐的9项组件/核心回归由`portable_cases.json`定义，使用包根`sim/run_rtl.py`统一暂存和运行，命令及XSim版本要求见[复现说明](reproduction.md)。

推荐回归所需输入已随包保留。运行时的XSim工作目录、日志、波形、数据库和生成文件由runner放到操作者指定的包外新目录。`source_archive/`中的其他历史工具保留原始开发路径，仅作为源码快照，不替代推荐的可迁移入口。

报告记录9项组件/核心回归通过，27条工具命令均成功且匹配通过标志，状态和范围见[RTL结果](../../report/reproduction_rtl.json)。交付收尾没有再次运行仿真；组件结果不扩大为整网推理或实板验收。2026-11-03硬件源码构建按用户要求在最终布线验收和bit/XSA导出前停止，见[硬件状态报告](../../report/reproduction_hardware.md)。
