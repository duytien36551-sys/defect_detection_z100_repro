# 工程技能与通用 PYNQ Skill

更新日期：2026-11-03。本目录共七项技能：五项Zynq/训练工程验证技能、一项Vivado布线分析文档技能，以及一项可单独申报的通用PYNQ诊断技能。

**通用PYNQ加分申报项：** [pynq-overlay-diagnostics](pynq-overlay-diagnostics/readme.md)。评委可直接阅读[独立申报说明](../report/pynq_skill_submission.md)，按第七节运行演示与测试。该技能面向PYNQ框架，不依赖本队PCB/PIN检测题目；工程原有技能继续保留，各自的验证成绩分别记录。

| 材料 | 数量 | 已有验证 |
| --- | --- | --- |
| Zynq/训练工程验证技能 | 5 | 合计62项历史工具测试，本次未重跑 |
| Vivado布线分析文档技能 | 1 | 工作流、报告模板与合成示例，无独立工具测试 |
| 通用PYNQ Overlay与DMA诊断 | 1 | 32项软件测试、6项静态演示、2项独立智能体使用检查，已完成隔离解压复测 |

## 目录结构

```text
skill/
  readme.md
  zynq-model-identity/
  zynq-inference-parity/
  zynq-ps-pl-performance/
  zynq-dma-debugging/
  detection-training-audit/
  vivado-routing-optimization/
  pynq-overlay-diagnostics/
```

前五项完整技能的内部结构包含 `skill.md`、`readme.md`、`scripts/`、`assets/`、`examples/`、`references/` 和相应的 `evidence/`、`validation/`。Vivado 布线优化文档技能是精简结构：`skill.md` 为入口，`readme.md` 介绍用途，`references/` 提供操作流程和经验，`assets/` 提供报告模板，`examples/` 展示合成数据如何分析；没有自动化脚本、证据目录或验证成绩。部分技能含 `agents/` 配置，供支持该格式的宿主使用。

## 使用方式

先根据问题选择一项技能，阅读该目录中的 `readme.md` 或 `skill.md`，按提示词提供工程路径和目标；前五项技能可按文档运行相应只读脚本，最后填写 `assets/` 内的报告模板。Vivado 布线优化项没有脚本；先按其工作流收集运行身份和阶段报告，获得授权后才设计最小对照实验。所有输入和结论都应保留来源，不存在的测量结果填写为未知或未运行。

不使用智能体时，也可人工按这些步骤操作。使用 Codex 时，将选中的技能文件夹复制到自己的 skills 目录，并将副本中的 skill.md 改名为 SKILL.md 后加载；提交工程中的文件保持小写。前五项技能的脚本使用Python标准库，支持的输入格式、参数和退出码见各目录说明；Windows环境有实际验证，Linux及Python3.9未单独实测。Vivado 文档技能没有脚本，阅读材料不要求安装 Vivado。

## 一 模型与平台身份核对

目录：zynq-model-identity

适用范围：换板、换权重、分辨率、类别或部署版本冲突。

使用步骤：根据当前用户目标建立目标配置、离线候选、实际运行三列。核对类别顺序、输入、预处理、协议、权重与模型包SHA，再将ELF、XSA、bitstream和运行时间对应起来。明确区分本次重算与原报告声明。

可复制提示词：

> 请核对本工程的目标、离线候选和实际运行身份，逐项给出证据时间、SHA、冲突和缺项，先做只读检查。

失效条件：模型哈希或HELLO一致不能证明全部硬件和固件已在这次运行；缺少加载身份或原始文件时，只能报告未确认。

已验证效果：两个本地案例及有限外部静态复用有记录；独立审查保留了仅声明身份，不将后构建清单当先前运行证明。

提炼来源：来源是目标权重被纠正，以及构建和运行记录时间不一致。 各目录中的 evidence/collaboration_chain.json 保留来源索引，references/lessons.md 及本目录 readme.md 保留经验说明。

## 二 分层一致性与量化检查

目录：zynq-inference-parity

适用范围：浮点、整数参考、C/RTL或实板输出不同，需要定位最早不一致层。

使用步骤：先固定同模型、同输入、同预处理、dtype、形状和布局，再比较原始字节或显式容差。检查舍入、饱和、尺度及参考生成时间；把执行一致与精度评价分别报告。

可复制提示词：

> 请按浮点、整数参考、C/RTL和实板逐层比较这些输出，先确认契约，定位最早差异，单列精度及缺失证据。

失效条件：契约不一致、缺少一侧原始输出、采集后更新参考时，结论需限定；单图一致不等于全数据集精度或量化通过。

已验证效果：历史二进制比较和采集包审查有记录，14项工具测试通过；没有把它写成新的推理或完整实板验收。

提炼来源：来源是Python参考与板端舍入差异，以及检测头一致但量化精度仍失败。 各目录中的 evidence/collaboration_chain.json 保留来源索引，references/lessons.md 及本目录 readme.md 保留经验说明。

## 三 PS与PL性能分析

目录：zynq-ps-pl-performance

适用范围：检测耗时高，需要判断ARM、DMA、PL及后处理的瓶颈。

使用步骤：明确开始结束时刻、时钟、预热、样本数和计时包含范围；检查阶段是否嵌套，计算传输量并提出单变量对照，只有输出一致且同口径更快才采用。

可复制提示词：

> 请分析本工程的PS、DMA、PL和后处理耗时，核对计时范围与嵌套，给出有证据的瓶颈和下一项可比较实验。

失效条件：一次测量不能计算持续FPS或代表性P50/P95；时钟未确认、嵌套阶段直接求和或不同口径版本不能作可靠加速结论。

已验证效果：8项工具测试及真实profile适配有记录；单次数据的P50/P95保持空值，没有推断新平台性能。

提炼来源：来源是无收益打包方案被放弃，随后以差分和重复对照选择快路径。 各目录中的 evidence/collaboration_chain.json 保留来源索引，references/lessons.md 及本目录 readme.md 保留经验说明。

## 四 DMA与缓存排障

目录：zynq-dma-debugging

适用范围：DMA卡住、长度或TLAST异常、缓存同步及初始化不稳定。

使用步骤：先保存运行ID和失败现场，核对发送及接收方向的地址、长度、状态、所有权与缓存操作。将原版、插桩版、断点及复位后的运行分别记录，按最小区分检查排除假设。

可复制提示词：

> 请整理这次DMA失败现场，检查长度、状态、缓存和缓冲所有权，分开各次运行，提出能区分原因的最小检查。

失效条件：快照不完整、不同运行拼接或诊断改变时序时，不推断唯一根因；技能加载本身不授权复位或重启硬件。

已验证效果：12项工具测试与独立时间线审查有记录；诊断早于失败的冲突被保留，不冒充本轮实板修复。

提炼来源：来源是诊断或断点后通过、未插桩原版仍失败，以及初始化影响结果。 各目录中的 evidence/collaboration_chain.json 保留来源索引，references/lessons.md 及本目录 readme.md 保留经验说明。

## 五 训练质量与收尾审计

目录：detection-training-audit

适用范围：数据来源隔离、验证集选模、质量报告、量化评价和指定轮次收尾。

使用步骤：核对来源分组、冻结划分和同一权重；分别报告训练/验证/测试、浮点/INT8/实板，保留逐类AP与召回、目标数、固定工作点P/R/F1及TP/FP/FN和正常图误报率；核对完整轮次和断点。

可复制提示词：

> 请按冻结验证规则核对同一最佳权重和完成轮次，分集合及后端提供完整质量证据、缺项和收尾状态，不用测试集选模。

失效条件：测试用于调参、权重或预处理混用、划分不明和后端未运行时，不补成成功；无正常图写不可评估。没有训练控制授权时不停止或恢复进程。

已验证效果：16项工具测试和200轮真实快照审查有记录；独立任务曾经路径澄清，未声明一次无协助完成。

提炼来源：来源是用户指定200轮收尾但原界面计划300轮，以及自动工作点、固定微平均和不同输入尺寸易混用。 各目录中的 evidence/collaboration_chain.json 保留来源索引，references/lessons.md 及本目录 readme.md 保留经验说明。

## 六 Vivado 布局布线分析

目录：vivado-routing-optimization

适用范围：检查 Vivado 实现时间、局部拥塞、时序收敛及检查点身份，并制定单变量对照实验。

使用步骤：先只读核对 run 身份、工具/器件/时钟、源码/XDC/DCP、阶段报告和机器负载；区分阶段检查点、最终实现、失败和用户停止。若确需构建，必须先明确授权、独立目录、资源预算、停止条件和验收门槛。

可复制提示词：

> 请按 Vivado 布线优化工作流先只读盘点工程，列出证据、未知项和一个最小对照实验，不要启动或停止构建。

失效条件：中间时序、route 迭代、overlap 数或进程状态不足以证明最终通过、完成百分比或 ETA；没有最终 route、coverage 和 DRC 报告时只报告已知阶段。

已验证效果：此项提供工作流、报告模板和合成示例，没有自动化脚本或独立测试记录；不扩充前五项技能合计62项测试的历史成绩。

## 七 通用PYNQ Overlay与DMA诊断（独立加分申报项）

目录：[pynq-overlay-diagnostics](pynq-overlay-diagnostics/readme.md)；[技能入口](pynq-overlay-diagnostics/skill.md)；[独立申报说明](../report/pynq_skill_submission.md)。

用途：在部署前检查bit/HWH/XSA目标器件与IP，核对DMA字节数、缓冲容量、偏移和对齐；静态审查PYNQ notebook中的Overlay加载、allocate、DMA传输与等待调用；在已有PYNQ系统内采集版本和Overlay元数据。采集器使用download=False，不下载bitstream或执行DMA。

通用性：换题目主要修改shape、dtype和IP契约；换板卡时提供该板自己的bit/HWH并更新器件/IP路径。同一套脚本可用于图像、信号等AXI流任务，无检测模型、类别或板端地址硬编码。不同器件的bitstream不能直接互换。

在工程包根目录验收（Python标准库即可，结果写到包外）：

```text
python -B skill/pynq-overlay-diagnostics/scripts/run_examples.py --out-dir ../pynq_demo_results
python -B -m unittest discover -s skill/pynq-overlay-diagnostics/tests -v
```

已有证据：32项软件测试和6项静态演示通过，使用真实7020/7100元数据及公开PYNQ缩放notebook；2项独立智能体使用检查经主线程查看实际产物，独立ZIP在隔离目录解压后复测通过。详见[验证说明](pynq-overlay-diagnostics/validation/acceptance.md)。缺BIT或物理地址时报告INCOMPLETE，发现冲突时报告BLOCKED，这些诊断状态不代表硬件运行成功。

申报口径：本项面向赛方“通用PYNQ Skill”独立评审，不将旧7020/7100原生C/ELF/JTAG运行记录算作PYNQ实测。本轮未做PYNQ实板推理，运行采集器PYNQ分支使用软件替身验证。加分以完整赛规及赛方评审为准。

## 前五项技能的工具与证据材料

前五项技能的提示词和工作流写在各自 `skill.md` 与 `readme.md`；案例报告模板位于 `assets/validation_report_template.md`；校验脚本位于 `scripts/`；经验说明位于 `readme.md` 与 `references/lessons.md`。Vivado 布线优化项是文档技能，其工作流与经验位于 `references/`，模板在 `assets/validation_report_template.md`，合成示例在 `examples/`；它没有脚本、独立证据或验证记录。以上文件均随工程包提供。

## 验证和能力范围

原五项工具共62项测试通过，这些是技能各自记录的历史结果，本次交付未重新运行工具测试。历史独立任务与组合案例是有限材料审查验证，同平台子代理不等于陌生人类队伍。新增独立通用PYNQ诊断技能见下节；本轮完成其软件测试和静态跨工程复用，不申报两板PYNQ推理实测。旧五技能的62项历史测试与新技能结果分开记录。完整硬件工程、原始训练集和板端固件属于整个作品材料，不由技能包代替。

## 许可

前五项工程验证技能与新增PYNQ技能各自携带MIT许可文件license。PYNQ公开缩放notebook的BSD-3-Clause许可、固定提交和来源哈希随包保留，见该目录third_party_notices.md；Vivado文档技能按其随附材料范围使用。
