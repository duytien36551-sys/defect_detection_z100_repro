# 仿真与检测复现

当前包提供epoch200源码和300张筛选图片/标签。`verify_submission.py`检查工程包文件清单和小写ASCII命名；`verify_model.py`检查当前模型契约。检测环境与复现命令见[固定模型检测说明](detection_reproduction.md)，RTL仿真见[可迁移RTL入口](rtl/readme.md)。

## RTL 组件回归

`run_rtl.py`可运行 9 项 RTL 组件/核心回归。测试台、RTL/include、ROM 和期望值位于 `rtl/`，案例索引见 `rtl/source_inventory.json`。Vivado/XSim 运行时日志、波形、数据库和工作快照应由操作者写入包外的新目录。

既有9项回归的报告状态为`PASS_NINE_FRESH_COMPONENT_TESTS`，见[RTL结果记录](../report/reproduction_rtl.json)。这些组件/核心回归曾通过各案例标记，工程包整理期间没有再次启动RTL仿真；它们不证明整网检测推理，也不构成板卡验收。

## 固定模型检测

`reproduce_detection.py`对冻结epoch200模型执行300张保留样例的整数参考检测。既有摘要见[检测结果记录](../report/reproduction_detection.json)：300张均与离线整数参考匹配，最大绝对误差为0。它是固定输入输出复现记录，不是代表性精度或吞吐率评测。

上述检测结果产生于数据路径去重之前；随后只调整了包内相同文件的存放路径，摘要的`delivery_layout_note`记录了路径别名和未重跑推理这一事实，不应解读为数据清理后的新一轮执行。需要复现时按[检测复现说明](detection_reproduction.md)在包外新目录运行。

## 旧版检查脚本

`verify_baseline.py`仅供追溯旧首次跑通版本。它依赖的 epoch108 数据及旧版 bit/ELF/XSA 已从精简包移除，不属于当前工程包入口。当前模型检查使用 `verify_model.py`；当前 RTL 与检测复现分别使用 `run_rtl.py` 和 `reproduce_detection.py`。

2026-11-03的30次scoped-mode JTAG请求和ABABA原始输出摘要副本现保存在[板端证据目录](../board/evidence/pc_fast_20261103/runtime_identity.json)、[连续请求记录](../board/evidence/pc_fast_20261103/continuous30.json)及[原始头对照](../board/evidence/pc_fast_20261103/raw_parity_summary.json)。它们与本目录CPU整数参考和RTL回归报告分开；完整缓存策略边界及外部scoped启动依赖见[板端交付索引](../board/readme.md)。包内没有整网RTL推理或新源码构建后的板卡验收结果。
