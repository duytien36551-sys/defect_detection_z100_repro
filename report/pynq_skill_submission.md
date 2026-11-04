# 通用PYNQ Skill申报说明

申报技能：pynq-overlay-diagnostics 1.0.0，PYNQ Overlay与DMA通用诊断。

技能面向PYNQ的Overlay、ip_dict、allocate/DMA和notebook工作流，可检查任意工程的目标器件、IP路径、传输字节数、DMA容量/偏移/对齐及API调用；板端采集器采用download=False并避免实例化DMA驱动。核心代码不包含本队缺陷类别、模型权重、推理协议或板卡固定地址。

换题目时更新shape、dtype和IP契约；换板时更换该板bit/HWH并更新器件与IP路径。使用7020、7100真实HWH片段展示同一工具对不同平台的诊断，使用公开PYNQ-HelloWorld图像缩放代码展示本队题目之外的复用。

## 评委可直接运行

在工程包根目录执行：

    python -B skill/pynq-overlay-diagnostics/scripts/run_examples.py --out-dir ../pynq_demo_results
    python -B -m unittest discover -s skill/pynq-overlay-diagnostics/tests -v

六个演示和32项测试已在Windows/Python3.12通过；独立ZIP在隔离目录解压后复测通过，另有两项独立智能体使用检查，主线程已核对实际配置、JSON及报告。这些均为软件/静态检查。报告中的BLOCKED/INCOMPLETE为发现配置冲突或缺少信息，不被包装成硬件成功。原始说明入口为skill/pynq-overlay-diagnostics/skill.md，安装到Codex时将副本入口改成SKILL.md。详细输入、输出及验收证据见同目录readme.md、references/与validation/。

## 规则对应与范围

用户提供的规则截图说明“面向PYNQ框架且不与本队题目绑定（换题目、换板卡仍可用）”可另行加分。该技能按这些通用条件提供可复用工具、示例与证据供评审。截图未给出完整3.3.2、分值或固定样本数量；本材料不保证评分结果。

本轮未在物理板卡运行PYNQ推理。旧7020/7100原生C/ELF/JTAG结果仅是工程背景，未计作PYNQ运行成绩。该技能申报能力是通用诊断和环境采集，非自动转换整个裸机推理链。原创MIT许可和外部BSD-3-Clause来源均随包保留。
