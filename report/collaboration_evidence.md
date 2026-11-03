# 大模型协作证据与技能提炼记录

本记录依据既有归档的选定用户提示、助手回答摘录及文件核查结果整理。引述内容来自原记录；摘要不是重新构造的对话，未提供隐藏推理。每条来源的 thread、turn、message ID、归档 SHA 及字段指针见 report/skill_package_evidence/cases/collaboration/chains.json。完整私人归档不在本次提交包中；选择性摘录不足以证明所有开发过程。

## 阅读顺序与对应材料

|案例|用户任务和协作结果|提炼技能|证据性质|
|---|---|---|---|
|模型选择|用户纠正目标模型，重新核对候选身份|zynq-model-identity|原始对话摘录，历史执行成绩为聊天陈述|
|数值差异|核对参考舍入方式后重新比较输出|zynq-inference-parity|原始对话摘录；不能替代模型质量|
|性能优化|放弃无收益方案，以差分及重复对照筛选快路径|zynq-ps-pl-performance|原始对话摘录；历史计时未重新运行|
|DMA异常|区分诊断版、原版、断点及初始化后的运行|zynq-dma-debugging|原始对话及独立fixture，根因不作过度推断|
|训练收尾|用户授权200轮收尾，核对轮次与冻结权重|detection-training-audit|对话与完成报告交叉核对|

## 智能体工作流

实际验证采用材料准备、独立执行、主线程核对原始输出的流程。独立执行者为同平台子代理。1.2.0补充验证覆盖五项有限任务和一个两轮组合案例，训练任务经过一次路径澄清；不是陌生人类队伍复用或宿主自动触发率证明。具体提示见 report/skill_package_evidence/cases/amd_readiness/completion/identity_dma/assigned_task_prompt.md，训练首次任务见 report/skill_package_evidence/cases/amd_readiness/completion/training/initial_attempt/prompt.md，组合记录见 report/skill_package_evidence/cases/amd_readiness/completion/multiturn/round1.md 和 round2.md。

## 后续开发纠错

report/correction_log.md 记录本次基线身份核对与两版本提交整理。下列技能协作摘录是通用技能来源材料，不作为本提交包的其他部署版本或性能成绩。

## 已选定原始协作链

# 五技能真实协作来源链

本附录只整理允许读取的本地归档、技能 `references/lessons.md` 和指定案例 `inputs/`。原始用户与助手文字按归档消息 ID 引用；没有补写缺失对话，也没有把独立运行并成同一次执行。

## 证据范围与核验

- 写入范围：本目录。归档 JSON 页 SHA-256 已与 archive manifest（原件见内部评审档案） 核对；各页哈希和逐条引用在 chains.json（文件：./collaboration_sources.json） 中。
- 五个技能均读取了对应的 `references/lessons.md`。这些文件的 SHA-256、归档页哈希、每条原始消息的 page/thread/turn/message ID、案例输入哈希、JSON Pointer 与二进制偏移均列在 JSON 中。没有读取技能 `skill.md` 或 `workflow.md`。
- 用户和助手消息来自本地历史文本归档。除训练收尾链外，归档的执行数据主要是当时助手的聊天报告；报告提到的历史验收报告和绝对路径未在本次允许范围内打开。
- 操作仅为 PowerShell UTF-8 读取/JSON 解析、关键词筛选、SHA-256、日志行号与 `Format-Hex` 查看；未控制板卡、联网、安装包、训练、推理或运行输入代码。

## 1. `zynq-model-identity`：部署前纠正目标模型身份

归档：v8deploy_older_2.json（原件见内部评审档案），SHA-256 `1cd78068641c1833054c69107db13a5e79db777fe8b4c22ec2b58bcc813ec1de`，thread `01a13ece-2d42-7be1-98a5-7f30a6e09c61`，turn `01a15195-b586-77e2-b97a-59879d4c5ab0`。

用户先说：

> 现在先把目前效果最好的模型部署到板端

助手先提出核对当前最佳权重、量化包和部署身份，并保留回退版本（message `msg_0dab378e239e39a1016ad565d6aa38819b9057b79b60f41293`）。用户随即更正：

> 目前效果最好的应该是两个77左右的模型

助手确认目标是 PCB、光电两项 AP 均约 77%，并避免部署此前提到的 76%／66% 版本（message `msg_0dab378e239e39a1016ad566367eac819b8ee7f67ad8db7bdb`）。随后助手报告选中本阶段第 28 轮，AP50 为 PCB 76.07%、光电 77.84%（message `msg_0dab378e239e39a1016ad566693724819b9f24bcd6f2c625b7`），并报告 JTAG 下 21 次请求通过、中位约 1.563 秒（message `msg_0dab378e239e39a1016ad569705e20819bafead0e05a2d60a3`）。

**结论与边界：**目标更正改变了要部署的模型版本，助手报告按更正重新选择、部署。后续全量 INT8 评估报告未达到原定质量目标；最终说明当前是 JTAG 临时运行、SD 未更新（messages `msg_0dab378e239e39a1016ad56c5b5608819ba62c2903985b57d5`、`msg_0dab378e239e39a1016ad56c823ca8819b998b282ffc8c5ae5`）。这条历史链没有可允许读取的权重/ELF/XSA/验收文件，所以模型选择与实板结果仍属聊天报告，冷启动也未证明。

## 2. `zynq-inference-parity`：先修正参考精度，再报告字节一致

与身份链共享上面的真实部署轮次和用户原始请求。检测头比较时，助手报告 Python 参考末步用 float32 相乘，而板端使用 double 相乘后转 float32；它按板端规则修正参考后报告 PCB 的 291,018 个值逐字节一致（message `msg_0dab378e239e39a1016ad569144034819baf212d444fa42baa`）。之后又报告 PCB 与光电检测头都与新模型参考逐字节一致（message `msg_0dab378e239e39a1016ad56943a730819ba77958de37ada563`）。

**结论与边界：**聊天记录展示了“先比较、发现参考舍入不一致、修正参考、再复比”的过程，也明确说没有修改板端计算迁就参考。原始检测头和修正后的参考文件未在允许来源中，因此字节相等仍是助手报告。它不代表模型质量通过：同轮报告光电 AP50:95 下降 3.78 个百分点，超过 2 点目标；SD 冷启动仍待验证。引用仍见 `v8deploy_older_2.json` 的同一 SHA 与 turn。

## 3. `zynq-ps-pl-performance`：小范围打包优化经重复对照

归档：v8deploy_older_3.json（原件见内部评审档案），SHA-256 `65a7718dfe421e1d67274e1c35e5d20a980f684df11ac75247db4a116140b169`，turn `01a14d3f-9303-7553-9861-17a02d61ad1f`。先前建议指出数据搬运比继续加并行路数更值得优先检查（前一 turn `01a1450c-d35d-77d0-b929-5c770f264207`，message `msg_0dab378e239e39a1016ad2305d0410819bad735d3d20fc9ed0`）。用户接受：

> 按照你的想法优化

助手计划以 1.672 秒版本作基线，单独建候选并要求输出一致且实际更快才采用（message `msg_0dab378e239e39a1016ad449a43794819bb3b67b35d6dd3be8`）。简单 1×1 打包改写没有减少 ARM 指令，于是放弃，改做 3×3 卷积内部区域快路径，边缘保留原逻辑（message `msg_0dab378e239e39a1016ad44a416c04819bbc8707cc8c629296`）。助手接着报告 106 组差分通过，并称两组对照合计 40 次请求和 7 项边界用例通过；最终汇总网络中位耗时约从 1.66–1.67 秒降到 1.59 秒，约快 4.5%（messages `msg_0dab378e239e39a1016ad44ac43360819bb11e6bf914d4c6bc`、`msg_0dab378e239e39a1016ad44c568a0c819ba10650616d2596cd`、`msg_0dab378e239e39a1016ad44c83a534819b9e1d65f5f95f6182`）。

**结论与边界：**这是对失败小尝试做取舍、限定快路径、再重复实测的真实聊天链。具体两组速度和差分结果未由允许范围内的历史报告独立核验。聊天明确说明计时包含传图与结果返回，不含电脑预处理和界面绘制；SD 文件未替换。历史链接的 `acceptance_result.md` 未打开。

## 4. `zynq-dma-debugging`：64 路的失败、插桩、原版复测与完整初始化

主链来自 v8deploy_older_5.json（原件见内部评审档案），SHA-256 `521ecae3f6cb196f8911b84c2f5d6fc815f4d34662415ffd147a5ae248e5a4fb`，thread `01a13ece-2d42-7be1-98a5-7f30a6e09c61`。用户说：

> 改用64位试一下

助手将其解释为 64 路输出通道并行，建议独立候选并保留已验收的 32 路版本（turn `01a13fcc-35f9-7bd3-9007-d216527c5598`，messages `01a13fcc-364a-7170-922b-610adc8bd17e`、`msg_0dab378e239e39a1016ad0d8230838819b9a296ae010348c6b`）。同页的 32 路比较基线聊天报告 20 次通过，中位 3.859 秒（turn `01a13f98-76b6-7e81-a656-2ca52205fe88`，message `msg_0dab378e239e39a1016ad0d5f5df48819b969c7a99cb7d2bec`）。

64 路首次上板的第一张 PCB 在约 1.36 秒时失败；助手定位第 37 节点、第二组 64 路输出，并加入只保存实际 LOAD 数据的 ARM 诊断快照（turn `01a140b9-f3a1-7530-a429-593de350da14`，messages `msg_0dab378e239e39a1016ad11c50f56c819b8032f287163203f2`、`msg_0dab378e239e39a1016ad11d4ea41c819b852a56a8e5c7f3f0`）。诊断版随后报告 20 次请求通过，但未插桩原版再次失败且停在不同位置，助手明确说诊断通过不证明问题解决（messages `msg_0dab378e239e39a1016ad11ece0e38819bb2489391071f5fd1`、`msg_0dab378e239e39a1016ad11f350924819bbc16c6093eb8394a`）。

随后硬件断点读到长度 1,984 字节和正确源地址，暂停后原版两张图通过；助手指出断点改变时序，不能算修复（message `msg_0dab378e239e39a1016ad122a065dc819b8356f9eef669c937`）。完整初始化后又有 20 次通过；两次独立复位总计 40/40 通过，检测头逐字节一致。最终报告约 3.38 秒/张，比 32 路约快 12.5%，同时仍明确根因未完全定位、SD 冷启动待验（messages `msg_0dab378e239e39a1016ad124c3aab8819bb16c9ad184615b8c`、`msg_0dab378e239e39a1016ad126c6a708819bbe893a4b800f7b45`、`msg_0dab378e239e39a1016ad1270f35f8819bbf19e5ad49a51d06`）。

**结论与边界：**完整的 64 路协作链来自历史聊天，但实板、计时与差分数据仍是当时助手报告，链接的 `tile64_production_result.md` 未打开。诊断版、原版、断点和完整初始化是分开的执行，不能互相替代为“修复证据”。本附录不推断唯一根因。

### 单列的 DMA 案例输入冲突（不与上述历史链拼接）

案例 `08_dma_cross_run_failure/inputs/` 是另一组 fixture。`failed_run_acceptance.json` 记录 1/2 结束且失败；`later_diagnostic_acceptance.json` 记录 20/20 成功，模型 SHA 相同。但所谓 `later_diagnostic` 的 `started_at_utc` 为 `2026-10-15T18:41:21.113766+00:00`，比失败运行 `2026-10-15T18:44:38.001238+00:00` 早 196.887472 秒，因此它不是失败之后的修复结果。构建报告只确认 XSA 元数据，注明实板 DMA 位宽未核验。

该 fixture 的 `failure_snapshot_manifest.json` 声明保存并恢复 XSDB host access 初值；`snapshot_xsct.log` 第 1 行却记录初值 `0`，第 25 行记录 restored=`1`。第 26–27 行报告 CPU 已恢复、snapshot PASS，但不能从这些行证明 host access 回到了初值。92 字节 DMA 寄存器文件的偏移和值见 JSON 中 `dma.fixture.snapshot_registers`；这里只记录观察值，不把状态码解释成唯一机制。

## 5. `detection-training-audit`：用户同意 200 轮收尾，输入文件核对完成

归档：01a15bc5-17ba-7d80-a6ba-3f28ffe04ac7.json（原件见内部评审档案），SHA-256 `a3406766b9dd8f4c0906aae1ea0ba1d329047a5f56f2b1f044b251150d962b54`。用户询问是否还要继续训练，助手分析第 107、160、179 轮：AP50 为 97.18%、97.11%、97.07%，AP50:95 为 76.85%、78.35%、79.09%，FP 为 167、132、121，FN 为 123、130、132；据此判断 AP50 近平台、定位指标改善但漏检没有改善，建议第 200 轮检查收尾（turn `01a1685d-bf88-7fd2-a0c8-de7a6e89fde4`，user `01a1685d-bfcc-76e3-9add-bd4708050327`，assistant `msg_02d39ccfeca5c48b016adb3ae2cae887d0b7ba075ce41577ed`）。中间轮次变化是聊天报告；允许的最终输入文件不含这些轮次的逐轮校验。

用户回复：

> 可以 按照200轮收尾的想法来

助手随后报告设置第 200 轮后收尾、保留学习率计划和完整断点、测试集不动（turn `01a1685e-c63f-79a3-b396-d2d5e27adecb`，message `msg_02d39ccfeca5c48b016adb3b1bafa087d0b1905d0fa327f059`）。在之后的效果汇报中，助手说第 200 轮完成且为最佳（turn `01a16d03-0748-7583-a2a8-05c42128036d`，message `msg_02d39ccfeca5c48b016adc6bb1067087d0a9d71a7cbe088d9f`）。

这条链有独立输入文件交叉核验：final_acceptance.json（文件：../skill/detection-training-audit/examples/10_training_gate_limits/inputs/final_acceptance.json） 记录连续 1–200 轮、没有第 201 轮、最佳轮为 200；final_report.json（文件：../skill/detection-training-audit/examples/10_training_gate_limits/inputs/final_report.json） 记录同一权重 SHA `2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6`，按冻结验证集 AP50:95 选模。其 800 张验证集 AP50/AP50:95 为 96.8636%/79.7333%，固定工作点 TP/FP/FN 为 2156/124/139；160 张原图子集为 97.1857%/81.2918%。这些文件哈希与字段路径在 JSON 中提供。

**结论与边界：**这是五条链中完成轮次、最佳轮次和权重身份有 fixture 文件交叉核验的一条。原计划 300 轮并未完成，这是用户同意的 200 轮收尾；验证无正常图片，正常图误报率不可评估。160 张子集来自同一验证源，不是独立盲测；文件未评估测试集、INT8、实板或业务验收。
