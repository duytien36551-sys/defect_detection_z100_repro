# PYNQ 运行语义与最小排障

本技能关注 PYNQ 框架自己的 Overlay、元数据、缓冲及驱动行为，而不实现检测模型。任意任务均可在明确输入输出契约后复用这些检查。

## 身份与加载

Overlay 默认可下载 bitstream。盘点时使用 Overlay(bitfile, download=False)，只读取 ip_dict 和参数。它是板端软件调用，不保证任何硬件已加载；is_loaded 只是 PYNQ 管理的加载状态，不是 bitstream 内容或整机功能的独立证明。配对 HWH 应与 BIT 同文件名主干，同构建导出。PYNQ 版本、板卡 image、设备支持和 FPGA manager 的实际可用性需要本机记录。

不要将“只读”盘点写成 overlay.axi_dma_0.register_map。属性访问可构造驱动；所核对的 PYNQ v3.0.1 AXI DMA 通道构造会调用 start，涉及 MMIO。采集器只使用 ip_dict，不实例化 IP 驱动、不读写 MMIO。

## 缓冲、缓存与传输

PYNQ DMA 使用 pynq.allocate 分配的连续缓冲，普通 numpy ndarray 不等价。记录 shape、dtype、nbytes、物理地址、start和所有权；缓冲在传输未完成时不可释放或由CPU改写。只有完成事务后再释放，异常现场先保留状态，不能自动复位后继续当作同一次成功。

在核对的 v3.0.1 simple DMA 实现中，发送 transfer 会 flush，接收完成 wait 会 invalidate。是否自动同步应以当前安装驱动为准，不能从 notebook 没有显式 flush/invalidate 就判定错误；也不能在设备持有缓冲时任意同步或改写。旧 notebook 使用 Xlnk/cma_array 时，需按所装版本迁移为 allocate，并重新核对缓存语义。

先根据实际流拓扑确定接收端就绪、发送与 accelerator start 的顺序。对于输出受下游背压影响的核，应先准备接收。DMA完成依赖 AXI-Stream 合同，尤其 TLAST、字节数和TKEEP。图像缩放、卷积、FFT的输入输出长度可能不同，切块必须同时约定核的帧边界；不提供“任意切片即可修复”的通用代码。

## 卡住时的最小检查

保留同一会话、同一硬件的两方向状态：输入/输出物理范围、分配容量、实际提交字节数、start、DMA参数、DMACR/DMASR、运行时间、TLAST/TKEEP观察及驱动版本。audit_overlay.py 的 --dmasr 只对已有数值解码，不访问硬件。

DMA Internal/Slave/Decode Error 是线索；先检查长度与通道状态、内存可达性和地址，不仅凭一个状态位给出唯一根因。wait() 可能一直轮询；外部 watchdog 能发现超时，不等于安全终止DMA或可释放缓冲。每次复位、重载、插桩须形成独立会话，不能拼成一条成功记录。

若用户授权实测：先保存原加载身份与失败现场，按已明确的板级流程执行一个最小用例，再保存输入、原始输出、参考比较、运行环境和起止计时。该步骤依赖真实板卡；软件替身测试或保存的 notebook 输出不能替代。

## 核对来源

PYNQ v3.0.1 固定标签提交 93ddd21ab623883590a8c8b07f0b157b2855da4b：

- https://github.com/Xilinx/PYNQ/blob/93ddd21ab623883590a8c8b07f0b157b2855da4b/pynq/overlay.py
- https://github.com/Xilinx/PYNQ/blob/93ddd21ab623883590a8c8b07f0b157b2855da4b/pynq/lib/dma.py
- https://github.com/Xilinx/PYNQ/blob/93ddd21ab623883590a8c8b07f0b157b2855da4b/pynq/buffer.py

这些链接用于核对API语义；不是声称当前板卡安装了这个版本。源码核对哈希见 validation/framework_sources.json。没有复制厂商驱动到本技能中。
