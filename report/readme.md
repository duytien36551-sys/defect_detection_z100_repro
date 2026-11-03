# 报告索引

本索引对应2026-11-03交付；记录文件中的历史结果保留原有身份和测量范围。

- `reproduction_validation.json`：本轮复现输入检查、实际构建/仿真/检测的统一验收状态；输入检查与实际执行分开记录。
- `reproduction_hardware.md`及同名JSON：源码交付、原最终平台历史结果及额外源码构建按要求停止的状态；不声称新bit/XSA导出通过。
- `reproduction_firmware.json`：BSP/FSBL/应用与BOOT构建、产物身份和待实板验收状态。
- `reproduction_rtl.json`：本轮9项RTL组件回归、27条工具命令及通过标志。
- `reproduction_detection.json`：已归档的300张电脑整数参考检测对照，模型和运行环境身份、容差、差异。样本是精选展示集，不是代表性或独立测试集；报告明确它不是打包期间的新推理。
- `engineering_package.md`、`missing_items.md`：交付范围与尚缺验收。
- `final_hardware/synthesis_implementation_summary.md`及同名JSON：原最终硬件综合/实现资源、时序、路由、DRC摘要与原报告哈希；不随包提供原始rpt。
- `sample_selection.json`、`test_sample_scores.json`：固定INT8评分规则与原800张逐图排序。
- `selected_sample_predictions.json`：交付300张的离线整数参考预测，作为复现对照输入。
- `cleanup_manifest.json`、`packaging_scope.json`：排除规则、最终上板文件身份及本版范围。
- `file_inventory.tsv`、`submission_sha256.json`：全部交付文件的大小和SHA256。
- `quality_summary.md`、`test_evaluation/`：历史完整800张内部测试结果，不能改称300张代表性指标。
- `documents/technical_document.docx`、`documents/technical_document.pdf`：当前赛方要求补充版28页技术文档，含完整封面和三级目录；原样同步，来源文件名和SHA见`documents/manifest.json`，三份旧稿不再随包提供。

随包收录的已有JTAG记录：[`continuous30.json`](../board/evidence/pc_fast_20261103/continuous30.json)记录网络修复版30次同一准备图像请求，全部匹配参考，`p50=362.42065 ms`、`p95=364.6278 ms`、`2.767125 FPS`；计时范围含TCP/HELLO、RGB传输、板端推理和响应校验，不含GUI等待。独立的[`raw_parity_summary.json`](../board/evidence/pc_fast_20261103/raw_parity_summary.json)记录五帧ABABA原始头比较全部匹配；[`runtime_identity.json`](../board/evidence/pc_fast_20261103/runtime_identity.json)记录既有运行的ELF和bit身份及限制。这些文件是README刷新时复制的既有证据，不代表打包期间新运行；测量限于同图重复与两图ABABA，不是代表性吞吐或数据集精度结论。历史`2.676367 FPS`仍只属于原归档运行。

历史来源JSON中的旧机器路径只用于追溯，不是本轮推荐构建入口的依赖。新构建产物、工具日志和运行快照均留在包外。
