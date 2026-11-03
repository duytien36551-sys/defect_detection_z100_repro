# 外部静态复用审查：PYNQ 图像缩放器

> 轮次说明：首轮只按自然语言任务选择并加载 `zynq-ps-pl-performance`；首轮报告原件保存在 `previous_pass/`。本轮由主线程明确指定加载 `zynq-model-identity` 与 `zynq-dma-debugging` 并逐工作流复核，不把后两项说成自动触发。

**首轮结果：部分适用，静态证据限定。** `zynq-ps-pl-performance` 1.0.0-rc1 可复用其“区分实测与估算、按数据流拆分计时、缺证据时不承诺 FPS”的审查框架；本材料不能证明技能在真实硬件上可复用，也不能据此给出板端性能结论。该技能描述面向 Zynq 检测链路，本样本是 PYNQ-Z2 路径下的图像缩放设计；MAC/检测后处理等项不适用，应换成像素流、DMA 字节数和图像正确性契约。

## 首轮范围与方法

- 目标：基于给定提交的静态源码和 notebook 已保存输出，审查平台/接口身份、PS/PL 数据流、DMA 契约、计时含义，并指出下一项最小检查。
- 写入范围：仅本目录的 `report.md`、`report.json`、`execution_log.md`。
- 读取范围：`external_reuse_20261025/inputs/**`、该目录 `source_manifest.json`，以及所选技能 `skill.md` 和 `references/workflow.md`。
- 未运行仓库、notebook、Vivado/HLS、硬件或测试；未联网、安装依赖、训练或推理。报告只描述静态证据，不代表在新板卡上的运行。

## 发现

### 1. 平台与接口身份

- README 介绍仓库覆盖多类板卡；这只是仓库级说明。具体提供的缩放 Tcl 路径是 `boards/Pynq-Z2/resizer/resizer.tcl`，脚本创建工程时指定器件 `xc7z020clg400-1`，并实例化 `processing_system7`。因此可确认该份 Tcl 的目标器件/PS IP；不能据此确认某一块实物板、当前加载的 overlay，或 notebook 保存输出来自这块目标板。
- notebook 加载文件名 `resizer.bit` 并取出 `axi_dma_0`、`resize_accel_0`；manifest 未列出 `.bit`、`.hwh`、Vivado routed timing 报告或实测日志。实际 bitstream/HWH 与源码是否匹配、运行板卡及软件环境均未评估。README 中的 PYNQ 2.7.0 兼容性是该 README 的声明，不是本次运行环境证据。

证据：`inputs/readme.md:20,32-39`；`inputs/boards/Pynq-Z2/resizer/resizer.tcl:44-50,128-133,235-303`；`inputs/pynq_helloworld/notebooks/edge/resizer_pl.ipynb:82-104`；文件范围见 `source_manifest.json`。

### 2. PS/PL 数据流与 DMA 契约

静态连接关系为：PS DDR → AXI DMA MM2S → 4-byte 到 3-byte AXI-Stream 转换器 → HLS `src` → resize → HLS `dst` → 3-byte 到 4-byte 转换器 → AXI DMA S2MM → PS DDR。DMA 两个存储器主端通过 interconnect 接 PS `S_AXI_HP0`；PS `M_AXI_GP0` 经 AXI-Lite interconnect 控制 DMA 和 resizer。Tcl 配置 simple DMA（`c_include_sg=0`）、MM2S/S2MM burst size 256；FCLK0 配置为 100 MHz。配置值不等于本次运行的实测频率或带宽。

HLS 源码声明 24-bit、`XF_8UC3`、NPPC1、双线性插值，最大编译图像 3840×2160。输入适配器按配置的行列数读流，输出适配器仅在最后一个像素置 `TLAST`，并令 `TKEEP=-1`。输入适配器读取 `TDATA`，不检查 `TLAST/TKEEP`，依赖尺寸决定帧边界。Notebook 先提交两个 DMA 通道，再写 resizer start，随后等待两个通道；尺寸寄存器在计时单元之前设置。缓冲区声明为连续、`uint8`、三通道，`cacheable=1`；所读代码没有显式 `flush`/`invalidate` 调用，缓存一致性行为因此未验证。

独立字节数计算：输入 `3840×2160×3 = 24,883,200` bytes；输出 `1920×1080×3 = 6,220,800` bytes；读入加写出名义数据量 `31,104,000` bytes。两个帧大小都能被 4 整除（分别为 6,220,800 与 1,555,200 个 4-byte word），但这只核对了尺寸算术，不能替代对 DMA 传输长度、`TLAST/TKEEP` 和缓存同步的运行验证。

**正确性疑点：** `xf_resize_accel_stream.cpp:52,84` 对二维行列循环使用 `i*rows+j` 作为线性 `Mat` 索引；若 `Mat::write/read` 按常规行主序线性索引解释，这里行步长应对应列数。按本次非方形尺寸独立计算，输入代码最大索引为 4,667,279，而完整行主序平面末索引为 8,294,399；输出分别为 1,167,239 与 2,073,599。索引区间会发生行间重叠，需先确认 vendor `Mat` 索引契约并做小尺寸验证。没有运行 C-sim 或硬件，故这是高优先级静态疑点，不是已观测到的运行故障。

证据：`inputs/boards/Pynq-Z2/resizer/resizer.tcl:199-232,235-303,311-333`；`inputs/boards/ip/src/xf_resize_accel_stream.cpp:10-21,25-30,32-55,57-89,91-117`；notebook `:228-236,290-300,307-331`。

### 3. 保存的 notebook 计时能说明什么

计时单元保存的输出是 `1 loop, best of 3: 247 ms per loop`（notebook JSON 行 395-410 中的输出和源码）。被计时语句包含 `run_kernel()` 和 `Image.fromarray(out_buffer)`；`run_kernel()` 包括 DMA transfer 调用、写 start 寄存器及两端 wait。图像打开、输入缓冲分配与拷贝、尺寸寄存器写入、overlay 加载在此前单元；`imshow` 在另一个单元。故它至多说明保存该输出的某次 notebook kernel 对这一组合代码路径记录了一个 best-of-3 标量。它不能拆分 PL、DMA、CPU/Python 或 PIL 转换耗时，也不能给出 P50/P95、稳态吞吐、延迟分布或可复现的当前板端基线。输出没有绑定板卡/bitstream/HWH、时钟/版本、时间戳、原始逐次采样或计时边界校准。

同一 Tcl 的 `check_resizer.tcl:4-16` 只扫描外部 routed timing 报告中的固定成功文本；manifest 没有该报告，所以脚本内容不能当作布线时序已通过的证据。`resizer.tcl` 中的 100 MHz 是设计配置值，不代表实际布线通过或实测运行时钟。

证据：`inputs/pynq_helloworld/notebooks/edge/resizer_pl.ipynb:395-410`（计时源码与保存输出）、`:228-236,269-275,290-331`（准备和 DMA 路径）、`:341-349,359-384`（单独执行/显示）；`inputs/boards/Pynq-Z2/resizer/check_resizer.tcl:1-16`。

## 下一项最小检查

在不执行 notebook 的前提下，先对这份精确 HLS 适配器做一个极小的非方形 C-sim（例如 2×3 RGB、每个像素带唯一行列标记），核对 `Mat` 线性地址、输入/输出像素顺序、字节数及 `TLAST/TKEEP` 终止位置。重点确认 `i*rows+j` 的实际语义；在确认正确性前不应把 247 ms 作为有效性能基线。随后若要做性能评估，再先将 `.bit/.hwh`、目标板/软件身份与源码提交绑定，并收集带计时边界和多次样本的实测分项及 routed 报告。

## 未评估项

- 实物板卡、overlay `.bit/.hwh` 的身份与一致性；运行 PYNQ/Vivado/HLS 版本。
- `xf::cv::Mat` 在该版本的索引实现、适配器 C-sim、端到端输出正确性。
- DMA 的实际地址/传输长度、缓存同步实际行为、AXIS 握手/背压和逐通道耗时。
- routed timing、资源利用率、真实时钟、带宽、连续帧吞吐、P50/P95、图像质量。
- 任何板端/硬件效果；本报告不推断新板运行。

## 哈希核对

8 个输入文件在编辑前均与 manifest 的字节数和 SHA-256 一致；最终再次核对均一致。`source_manifest.json`、所选技能 `skill.md` 与 `references/workflow.md` 的 SHA-256 前后未变，数值列于 `report.json`。本次没有改动技能或输入源码。

人工帮助：没有向用户请求额外材料或人工执行操作；技能由本审查者根据任务内容选择，独立计算和结论均来自上述允许读取的静态文件。

## 第二轮补充：主线程显式指定两个技能工作流

### 调用历史与新增技能文件

- 首轮收到的自然语言审查任务中，我只选择 `zynq-ps-pl-performance`，依据是任务围绕 PS/PL 数据流与计时证据；当时没有自动加载或声称调用身份、DMA 技能。
- 本轮由主线程明确要求 `$zynq-model-identity` 和 `$zynq-dma-debugging`。我实际读取了各自 `skill.md` 与 `references/workflow.md`，分别按身份表/缺项/下一项最小核查，以及 DMA 时间线/长度与帧边界/缓存与缓冲所有权/缺失状态证据执行静态审查。这是显式指定后的追加调用，不是首轮自动触发。
- 新加载文档的读取前后 SHA-256 列于 `report.json`；本次只读这些入口和工作流，没有打开技能引用的 lessons、examples、旧 results 或其他报告。

| 技能 | 入口 SHA-256 | 工作流 SHA-256 |
|---|---|---|
| `zynq-model-identity` 1.0.0-rc1 | `b9cc1d0c174832ec456d6b3a6261fa3418049fca48f297c7f05129f440adaca0` | `ec6fed552e1c548739884a1688a1fb36f5e1030fa70d70694ea7d1a4721b1ae3` |
| `zynq-dma-debugging` 1.0.0-rc1 | `e1fb05a68b58ffbe09af5ea0d522a462231319083233580ac0462d245faf2aff` | `fde5d9bfc6d58b642afc3d8a4db2892a5d6013443977809d1463a0579c66e909` |

### `zynq-model-identity` 工作流复核

按“目标配置 / 离线候选 / 已运行配置”区分证据：

| 身份层 | 允许材料能确认的内容 | 未确认项 |
|---|---|---|
| 目标配置 | Pynq-Z2 目录中的 Vivado Tcl 指定 `xc7z020clg400-1`，实例化 `processing_system7`；工程引用 AXI DMA、axis width converter、HLS `resize_accel` IP。来源 manifest 声明提交 `9728edf2ea6b7bc157acb126f773e93c3e9561c2`，于 `2026-10-25T15:19:34.544480+08:00` 获取。 | 该 Tcl 不是构建报告；未提供实际生成的 bitstream/HWH、XSA、工具版本、板卡序列/型号运行记录或 routed report。manifest 获取时间不是构建/运行时间。 |
| 离线候选 | 提供的 HLS C++ 源文件已按 manifest 重算 SHA-256，匹配 `3df90bf…e7970c`；源码声明 24-bit `XF_8UC3`/NPPC1 和最大 3840×2160。notebook 声明加载 `resizer.bit`。 | `resizer.bit` 和 `.hwh` 未包含在 manifest 输入中，不能将源文件身份绑定到实际 bitstream，也不能由 Tcl 配置推断已成功构建。 |
| 已运行配置 | notebook 保存了 `Overlay("resizer.bit")`、`axi_dma_0`/`resize_accel_0` 对象及 execution counts；README 声明兼容 PYNQ 2.7.0，notebook 元数据记录 Python 3.6.5。 | 以上 README/Notebook 字段不是同一次板端运行身份；无板卡型号/序列、运行时 PYNQ/Python、bit/HWH 哈希、执行时间或同次运行记录，不能确认实际部署/兼容。 |

输入契约方面，notebook 引用 `images/sahara.jpg`，保存输出显示源尺寸 3840×2160、按因子 2 变为 1920×1080，并分配三通道 `uint8` 缓冲。图片本体不在 manifest；notebook 没有把 Pillow mode / RGB 顺序作为运行断言。类别、权重和检测模型在这个 resizer 工程中不适用。协议方面，静态源码能显示 HLS AXIS 数据宽度和控制寄存器，Tcl 能显示 GP0/HP0 路由；但没有将一份已运行 overlay 与该寄存器/DMA 契约绑定。

**身份工作流结论：** 仅源码声明的目标器件、源代码和 notebook 期望文件名已核对。候选构建物与已运行硬件身份仍未确认；不得按文件名或 `execution_count` 宣称已部署、兼容或来自同一构建。最小身份核查是只读取得实际加载的 `resizer.bit` 与配对 `.hwh`，重算两者 SHA-256，并与这份 Tcl/manifest 提交、目标器件、IP 名称/寄存器映射以及板端 PYNQ 版本记录配对。

证据位置：`inputs/readme.md:20,32-39`；`inputs/setup.py:49-75`；`inputs/boards/Pynq-Z2/resizer/resizer.tcl:44-50,128-133,199-232,235-303`；`inputs/boards/ip/src/xf_resize_accel_stream.cpp:10-21,91-117`；notebook `:82-104,126-132,194-213,228-236`；manifest `source_manifest.json` 文件清单与 `acquired_at`。README 的多板支持和 Pynq-Z2 Tcl 是仓库级说明与具体设计目标的范围差异，不是实际跨板兼容证据。

### `zynq-dma-debugging` 工作流复核

**保存材料能排出的时间线（只有 notebook 代码顺序，没有可证明的同次运行时钟时间）：**

1. notebook cell execution count 2 加载 `resizer.bit`，count 3 取得 DMA/HLS IP 对象。
2. count 7 分配输入/输出连续缓冲，count 8 把 PIL 图像拷入输入缓冲；count 10 写入源/目标行列寄存器。
3. count 9 定义的 `run_kernel()` 先对 MM2S/S2MM 调用 `transfer()`，写 resizer start，再分别 `wait()`；count 11 曾调用该函数并生成 PIL 图像。
4. count 13 的 `%%timeit` 保存输出为 best-of-3 的 247 ms；它计时 `run_kernel()` 和 `Image.fromarray(out_buffer)`。

这些 execution counts 和输出没有时间戳、kernel session ID、DMA 寄存器快照、缓冲物理范围/实际传输长度或失败状态。它们不足以证明四个 cell 输出属于同一块板或同一次运行；也没有记录可供区分“成功/失败”的 DMA 事件。因此本材料不是一个已确诊 DMA 故障现场，不能依据该 debug 工作流给出 DMA 根因。

依工作流将可疑项分开：

- **数据与长度：** notebook 传入完整 ndarray 缓冲而未显式给长度；按形状可独立算出 24,883,200 / 6,220,800 bytes，但实际驱动提交的字节数没有运行记录。Tcl 配置 4-byte↔3-byte width converters；HLS 输入适配器按尺寸读取像素而不检查输入 `TLAST/TKEEP`，输出适配器对最终像素置 `TLAST`。这是源代码契约，不等于观测过 AXIS 帧尾。
- **缓存：** 缓冲设置 `cacheable=1`，所读 notebook 片段没有显式 `flush`/`invalidate`。按技能规则，驱动自动同步策略未知，不能仅凭调用端无同步 API 就断言缓存错误。
- **所有权与初始化：** 函数在返回前等待两个 DMA 通道，但没有 channel status、错误码、转移完成长度或初始化前后状态。当前没有现场状态可判定缓冲可安全复用；本轮没有复位、覆盖、重放或再次启动任何事务。
- **计算数据顺序：** 首轮记录的 `i*rows+j` 静态索引疑点仍在，但它不是已解码的 DMA 根因；需先用小尺寸适配器仿真区分。不能把潜在计算索引错误改写成 DMA 故障结论。

**DMA 工作流结论：** 静态能核对拓扑和调用顺序，不能判断 TLAST/长度是否在实际事务异常、缓存同步是否失败、或是否发生所有权/初始化问题。当前最小安全的下一步仍是不执行 notebook 的极小非方形 C-sim，检查索引和 stream 边界；若之后确有板端 DMA 失败，再先保存同一次运行的阶段、方向、实际长度、通道状态、缓存属性/同步、缓冲范围和初始化记录，按板级契约决定下一步，不自动复位或重放。

证据位置：Tcl `:199-232,311-333`；HLS source `:25-30,32-89,92-117`；notebook `:82-104,228-236,269-275,290-331,342-349,395-410`。新技能 SHA、首轮原件快照 SHA 与最后验证结果记录在 `report.json` 和 `execution_log.md`。
