---
name: pynq-overlay-diagnostics
description: 面向 PYNQ Overlay 的部署前检查和 DMA 故障初查。读取任意板卡工程的 bit/HWH/XSA、传输配置及 notebook，核对器件、IP、DMA长度和地址对齐；支持板端只读采集 PYNQ 环境。适用于图像、信号和其他AXI流任务，不绑定检测模型或本队板卡。
license: MIT
metadata:
  version: "1.0.0"
---

# PYNQ Overlay 与 DMA 通用诊断

为 PYNQ 使用者回答：当前元数据与目标器件是否相符、脚本要求的 IP 是否存在、DMA 的配置能否承载这次数据、还缺什么运行证据。输出可定位到文件哈希、IP 路径、参数和字节数的报告。

## 选择入口

- 有 bit/HWH/XSA，或换板后 IP 找不到、DMA 报长度/对齐错误：运行离线检查。
- 只有 notebook：先用脚本读取代码，不能为取证直接执行整个 notebook。
- 已在 PYNQ 系统，想确认环境和元数据：运行板端只读采集；它不会加载 bitstream，不进行 DMA。

板型、模型、类别、图像尺寸和 IP 名称从用户的工程/config 获取，不沿用示例值。没有 HWH 时报告缺失；不能从板卡名字推断寄存器地址，也不能把裸机 ELF/网口通信冒充 PYNQ 部署。

## 执行

1. 从当前工程查找目标器件、bit、同构建 HWH（或含 HWH 的 XSA）、notebook 和传输形状。发现多个候选，列出文件与构建来源再选；不拿同名文件当作同一版本。
2. 按 [配置契约](references/contracts.md) 创建 JSON。dtype、shape 是本次 DMA 缓冲的数据，而不是原始图片文件尺寸；start 是字节偏移。先核对打包/填充后的传输量。
3. 用当前 Python 运行脚本（均从技能根目录执行；可使用脚本绝对路径）：

   ```text
   python -B scripts/audit_overlay.py --hwh /path/design.hwh --bit /path/design.bit --config /path/contract.json --out /path/audit.json
   python -B scripts/audit_overlay.py --hwh /path/design.xsa --member system.hwh --config /path/contract.json --out /path/audit.json
   python -B scripts/inspect_notebook.py --notebook /path/example.ipynb --out /path/notebook_audit.json
   ```

4. 若用户正在 PYNQ Python 环境中且文件已明确，可运行：

   ```text
   python -B scripts/collect_runtime.py --bit /path/design.bit --out /path/pynq_environment.json
   ```

   先阅读 [PYNQ 运行语义](references/pynq_runtime.md)。禁止用 getattr(overlay, dma_name) 来完成“只读盘点”：PYNQ 驱动的构造可能启动通道。采集器只访问元数据，使用 download=False。
5. 按报告中的 error/unknown 区分已发现冲突和未验证信息。对于 DMA 超长，检查分块与 AXI-Stream 帧边界是否一致，不能只将 Python 数组切片后反复发送；对于缓存，先查实际驱动版本自动 flush/invalidate，不能因 notebook 没写这两个调用就断定错误。
6. 输出原因、原始参数、可复现命令、下一项最小检查。模板见 [报告模板](assets/report_template.md)。换题目主要改 shape/dtype 和 IP 契约；换板要提供该板自己的 bit/HWH 并改 expected_device，原 bitstream 不可跨器件复用。

## 结论边界

离线状态只表示本次静态检查：BLOCKED=发现冲突；INCOMPLETE=关键输入缺失；STATIC_CHECKS_PASSED=列出的静态检查通过。INVALID_INPUT=格式无效。任何状态都不代表推理正确、PYNQ 驱动兼容已实测或硬件运行成功。脚本不判断模型精度，不执行 notebook，不自行下载/复位/修改启动介质。

若已有 DMASR 快照，可附加 --dmasr 0x1002 离线解码。位含义是现场线索，不是唯一根因；先保留同一会话中方向、地址、长度、错误状态和时间，再设计最小复测。完整板端运行需额外记录输入输出、实际 PYNQ/板卡身份、TLAST、缓存/所有权和计时边界。

初次使用可运行 [可复现演示](readme.md)；真实工程来源和本次验收范围见 [验证说明](validation/acceptance.md)。示例元数据及软件替身测试不作为两块板的实机运行成绩。
