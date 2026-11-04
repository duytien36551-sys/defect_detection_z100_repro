# 通用 PYNQ Skill：Overlay 与 DMA 诊断

这是面向 PYNQ 框架的独立技能，帮助使用者在加载硬件前发现器件/IP不匹配、DMA传输越界和地址对齐问题，并只读审查已有 notebook。它不依赖本队的YOLO模型、PCB/PIN类别、私有协议或特定板卡地址。

换题目：修改输入输出 shape、dtype 和IP契约；图像、信号、矩阵处理都可复用。换板卡：换成该板自己的 bit/HWH，再改目标器件与完整IP路径，仍用相同脚本和工作流。不同器件的 bitstream 不能通用。

## 工程包内的独立申报位置

本技能是工程包中单独说明的“通用PYNQ Skill”申报项，与原有Zynq工程技能分开记录。工程包入口为skill/pynq-overlay-diagnostics/readme.md，独立申报说明为report/pynq_skill_submission.md，技能总目录为skill/readme.md；独立分发包中的本目录可单独安装和运行，不依赖这些外部说明文件。

评审可重点查看：references/contracts.md的数据/IP配置契约、scripts/下的通用工具、examples/中的跨任务与跨工程案例，以及validation/acceptance.md中的真实验证范围。核心代码没有模型、检测类别或某块板卡寄存器地址硬编码。

## 直接验收

在本目录运行（Python 3.9+，标准库即可；演示不会访问板卡）：

    python -B scripts/run_examples.py --out-dir ../pynq_demo_results

会产生六个报告和一份 summary.json：

| 案例 | 来源与任务 | 可观察结果 |
| --- | --- | --- |
| 7020 RGB小块 | 真实7020 HWH参数片段，64×64×3 uint8 | 计算12,288字节；对齐地址、bit配对未提供，保留INCOMPLETE |
| 7020 信号向量 | 同元数据，4096个int16 | 计算8,192字节；无需修改诊断脚本 |
| 7020 超长图像 | 同元数据，640×640×3 uint8 | 指出1,228,800字节超过16位长度65,535字节，BLOCKED |
| 7100 迁移检查 | 真实7100原生ACP工程参数片段 | 明确没有预期的AXI DMA，BLOCKED，不能套用标准驱动 |
| 7100 IP盘点 | 同元数据，检查自定义核 | 正确发现IP；无bit配对，保留INCOMPLETE |
| 外部PYNQ缩放任务 | 固定提交的公开PYNQ notebook源代码 | 识别Overlay/allocate/transfer/wait，完全不执行保存代码和输出 |

这些是静态软件检查，不是两块板卡的PYNQ推理运行成绩。两个板型和多个数据契约用于展示同一工具的复用，未将合成配置或历史原生检测包装成PYNQ实测。

现有验证：32项软件测试、6项静态演示及2项独立智能体使用检查，均经核验；独立ZIP解压到隔离目录后再次通过测试与演示。详见validation/acceptance.md、software_validation.json、forward_summary.json及portable_acceptance.json。独立使用检查来自同一环境中的智能体，不等于外部人类团队或实板验收。

运行测试：

    python -B -m unittest discover -s tests -v

## 在自己的工程使用

复制 examples/metadata_7020/rgb_tile.json 作为起点，按 references/contracts.md 修改；使用你自己的完整HWH/XSA，不把示例片段复制给Overlay加载。然后运行：

    python -B scripts/audit_overlay.py --hwh your_design.hwh --bit your_design.bit --config your_contract.json --out audit.json

在已安装PYNQ的板端，只读采集：

    python -B scripts/collect_runtime.py --bit /home/xilinx/your_design.bit --out environment.json

如果当前电脑未安装PYNQ，采集器必须报告不可用，不生成板端通过成绩。静态工具仍可使用。运行语义与DMA排查见 references/pynq_runtime.md。

## 作为智能体技能安装

独立ZIP中的文件夹直接复制到 Codex 的 skills 目录，其中 SKILL.md 是入口。工程提交包遵守小写文件名约定，将入口保存为 skill.md；安装该副本时先在副本中改名为 SKILL.md。文件agents/openai.yaml为自动发现提供描述，不要求安装其他技能。

示例提示：

> 使用 $pynq-overlay-diagnostics，检查这个PYNQ工程在换板后的Overlay、DMA字节数和notebook调用，先做离线检查；输出冲突、缺项和可复现命令。

## 申报范围

技能面向PYNQ Overlay和驱动元数据，可脱离本队检测任务使用；随包提供独立入口、脚本、配置、公开项目复用示例、测试、来源哈希和验收报告。可据此提交“通用PYNQ Skill”供赛方评审。截图未列明具体分值和完整3.3.2细则；最终评分由赛方决定，不声称已获加分。当前不申报两板PYNQ推理实测或无人帮助的硬件迁移成功。

原创代码与文档采用MIT许可，见 license。公开notebook的源代码衍生片段采用BSD-3-Clause，保留原许可及来源；不附其输出图片，不重新授权第三方素材。精简HWH片段仅用于元数据检查；不是厂商IP的再许可。
