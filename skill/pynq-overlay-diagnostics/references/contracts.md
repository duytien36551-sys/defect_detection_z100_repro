# 离线配置契约

配置为 JSON，schema 固定为 pynq-overlay-contract-v1；没有板卡、类别、权重和任务专用常量。脚本使用 Python 3.9+ 标准库，可在普通电脑运行；不要求安装 PYNQ。

    {
      "schema": "pynq-overlay-contract-v1",
      "name": "my-stream-task",
      "expected_device": "7z020",
      "required_ips": [{"name":"axi_dma_0", "vlnv_contains":":axi_dma:"}],
      "dma": {
        "ip": "axi_dma_0",
        "transfers": [
          {"direction":"mm2s", "shape":[64,64,3], "dtype":"uint8", "buffer_bytes":12288, "start_bytes":0},
          {"direction":"s2mm", "shape":[64,64,3], "dtype":"uint8", "buffer_bytes":12288, "start_bytes":0}
        ]
      }
    }

- expected_device 检查器件 die（如 7z020 / 7z100），不是电路板型号、封装、速度级或引脚约束验证。XC 前缀可省略；Zynq UltraScale+ 的 zu 标识也可读取，但未作该平台运行验证。
- required_ips 的 name 是完整层级路径，如 image_pipeline/axi_dma_0；不做模糊匹配，不自动选择第一个 DMA。vlnv_contains 是可选类型片段。
- dma 仅适用于 Xilinx AXI DMA 的 simple mode。没有 DMA 的设计应省略该项做元数据盘点，或保留预期 DMA 以获得明确的迁移阻塞结果；不可把 ACP 原生加速核按 AXI DMA 操作。
- direction 为 mm2s / s2mm。shape 是实际传输数组形状；dtype 只能取脚本列出的显式宽度类型。RGB 图像、FFT向量、分类特征都可用同一接口。
- buffer_bytes 是实际分配容量；start_bytes 是字节偏移，默认0。physical_address 只能填写本次实际分配地址；缺少时对齐标为未知，不用示例地址冒充实测。
- 单次 simple DMA 最大字节数为 (1 << C_SG_LENGTH_WIDTH) - 1。例如16位长度上限为65,535字节。图像大小乘 dtype 字节数后再比较。这个上限不能直接套用 SG 或 micro DMA。
- 非DRE地址对齐条件为 (physical_address + start_bytes) % (memory_map_data_width / 8) == 0；不凭数组维度推断物理地址对齐。
- 没有 bit 文件时，bit/HWH配对保留未知；即使器件相同，也不能证明是同构建。用构建清单绑定两者的 SHA、工具版本和源配置。

报告状态和退出码：STATIC_CHECKS_PASSED=0；BLOCKED=2；INVALID_INPUT=3；INCOMPLETE=4。INCOMPLETE 是有效结果，表示缺证据。命令返回0也不是硬件验收通过。

示例元数据是由真实 HWH 提炼的最小参数片段，不是可加载的 Overlay。examples/*/provenance.json 记录原文件及分发片段哈希。scope_note 和 name 仅供说明，不影响判断。
