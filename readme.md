# Z100 缺陷检测工程复现包

[![License: MIT](https://img.shields.io/badge/Original_code-MIT-green.svg)](license)

**公开源码仓库：<https://github.com/duytien36551-sys/defect_detection_z100_repro>**

项目原创源码采用赛题第 3.3.3.3 节推荐的 **MIT 许可证**，允许复制、修改和再分发，须保留版权与许可声明。第三方内容保留原许可，Ultralytics 相关内容的 AGPL 条款不被 MIT 替代。参见 [许可证全文](license)、[第三方许可与数据/模型授权范围](third_party_notices.md) 和 [开源发布说明](open_source.md)。公开仓库不代表数据再分发权或所有技术验收已完成。

快速入口：[技术文档 PDF](report/documents/technical_document.pdf) · [Word](report/documents/technical_document.docx) · [复现状态](report/reproduction_validation.json) · [检测复现](sim/detection_reproduction.md) · [待验收项](report/missing_items.md)

---

本包从冻结的 epoch200 模型出发，提供 RTL/PS/BSP/启动程序源码、构建入口、RTL 组件回归、300 张优选 test 样例、检测参考结果和最终上板文件。供赛方安装工具后重建并运行作品，不要求从零训练。README 更新于 2026-11-03，按最新交付文件及已有实测证据整理；本次说明更新未重新运行构建、仿真、推理或板卡操作。已有结果和停止状态见 `report/reproduction_validation.json`，尚缺结果见 `report/missing_items.md`。

| 目录 | 内容 |
| --- | --- |
| `src/` | 当前 RTL/ROM、PS、桌面程序、模型导出/量化及训练实现 |
| `sim/` | 9 项可迁移 RTL 组件回归、输入/模型校验、检测复现入口 |
| `build/` | 硬件/固件源码构建入口、BD/Tcl、BSP/FSBL 源码、依赖说明 |
| `board/` | 原最终 bit/XSA/FSBL、性能归档版 ELF、SD 网络修复版 ELF/BOOT、运行入口及历史板端结果 |
| `data/` | 300 对图/标签、冻结 PT/V8P、图与量化参数、参考数据及来源元数据 |
| `skill/` | 工程技能、说明和教学材料 |
| `report/` | 设计/资源/时序/质量摘要、现有结果、协作记录、最新 Word/PDF 技术文档和文件 SHA 清单 |

目录和文件名均使用小写 ASCII。构建/仿真输出目录须在包外；包内不附对象、静态库、DCP、工具日志、波形或仿真数据库。测试台读取的 ROM/输入/期望值属于复现输入，保留在 `sim/rtl/`。已有最终 bit/XSA/ELF/BOOT 作为上板交付和参考保留，不被新构建覆盖。

## 1. 环境与完整性

完整构建环境为 Windows x64、Python 3.12、Vivado/Vitis 2026.1（Zynq-7000 支持、ARM GCC、Bootgen），BSP/启动程序构建另需 CMake 和 MinGW Make。工具链由复现者自行安装，脚本通过参数接收安装路径，不需要原机器的工程目录。Python 3.10+ 可做标准库输入检查。整数参考依赖见 `sim/detection_reproduction.md`；GUI 依赖见 `build/requirements_desktop.txt`。

解压后，在含本文件的目录执行：

```powershell
python -B sim/verify_submission.py
python -B sim/verify_model.py
python -B build/prepare_dataset.py
python -B build/rebuild_hardware_source.py --check
python -B build/rebuild_bsp_sources.py --check
python -B build/rebuild_firmware.py --check
python -B build/rebuild_sd_boot.py --check
python -B sim/run_rtl.py --check
python -B sim/reproduce_detection.py --check
python -B board/run_desktop.py --check
```

`--check` 只检查输入，不表示已经综合、编译、仿真或上板。先通过文件 SHA 校验，再执行构建。

## 2. 最新版本与运行边界

- 模型固定为 epoch200、PIN 九类、640×640 INT8；硬件为 Z100、12 路、1252 DSP、100 MHz。模型、固件和 bit 的身份应分别核对，不能只看文件名。
- PC 检测界面已包含在 `src/desktop/`。安装 `build/requirements_desktop.txt` 后，可双击 `board/start_desktop.bat`，或使用本文件第 6 节命令连接板卡。界面提供连接/身份诊断、图片导入、检测框与类别/置信度显示、结果和历史记录；它不负责给板卡下载或复位。
- 最新技术文档为 [Word](report/documents/technical_document.docx) 和 [PDF](report/documents/technical_document.pdf)，共 28 页，含封面、三级目录和界面展示；文件来源与 SHA 见 `report/documents/manifest.json`。
- 已补入 2026-11-03 的网络修复 ELF **JTAG + 已获资格的 SCOPED 缓存模式**实板记录：30 次同图请求全部与参考检测一致，主机请求耗时中位数 **362.421 ms**、P95 **364.628 ms**，批次吞吐率 **2.767125 FPS**；另有两图 ABABA 五帧原始检测头逐字节一致记录。计时含 TCP/HELLO、RGB 传输、板端推理和响应校验，不含输入预处理及界面停留。证据见 `board/evidence/pc_fast_20261103/`。
- 该速度依赖外部 JTAG 启动/资格交接；自包含的 SCOPED 冷启动入口尚未随包提供。普通启动默认保守的 FULL 缓存维护，已有记录为 500 多 ms，不能只复制同一 ELF/BOOT 就承诺 362 ms。`board/final_run/launch.tcl` 是依赖外部工程的历史脚本。SD 镜像断电冷启动及 SD 自主 SCOPED 启动尚未验收。

上述重复请求与两图一致性记录不能代替全数据集实板精度、长期运行或独立生产批次泛化验收。原性能归档 ELF 的 2.676367 FPS 仍按原身份保留，不能与网络修复 ELF 混用。

## 3. 从 RTL 重建硬件

以下工具路径仅为示例，按自己的安装位置修改：

```powershell
python -B build/rebuild_hardware_source.py --build --vivado "C:\appload\2026.1\Vivado\bin\vivado.bat" --output-root C:/z100_hw
```

请选择包外、可写的短输出路径（例如`C:/z100_hw`或其他盘的短目录）；Vivado生成的BD/IP路径较深，过长的输出根目录会超过Windows路径限制。流程使用包内53份RTL/ROM和BD/Tcl，重新综合、布局、布线、优化及导出，不依赖旧DCP。每次运行建立独立目录，时序/路由/DRC验收通过后才导出`export/artifacts/z100_platform.bit`和`export/artifacts/z100_platform.xsa`。原始报告及中间产物留在包外运行目录。参数和策略见`build/hardware_source/readme.md`；源码材料与已有构建状态见`report/reproduction_hardware.md`，原最终平台摘要见`report/final_hardware/synthesis_implementation_summary.md`。

## 4. 固件与启动镜像

`build/rebuild_firmware.py` 构建性能归档版应用；`build/rebuild_sd_boot.py` 构建含网络修复的运行版。BSP 库和对象由源码在包外生成。命令、工具链路径、FSBL 和 BOOT 输入选择见 `build/firmware_portable/readme.md` 与 `build/sd_boot/readme.md`。

重建结果与原上板文件分别记录身份。生成 ELF 不能替代新产物的实板回归。使用新硬件产物制作 BOOT 时应配套使用同次导出的 bit/XSA；SD 步骤见 `board/sd_network_fix_v1/usage.md`。

## 5. RTL 仿真

```powershell
python -B sim/run_rtl.py --run --case all --vivado-bin "C:\appload\2026.1\Vivado\bin" --output-dir ../repro_output/rtl_all
```

共 9 项组件/核心回归，可先用 `--case unit01` 快速检查。runner 校验 SHA，执行 xvlog/xelab/xsim 并检查通过标志；工具失败或缺少标志均返回非零。详细说明见 `sim/rtl/reproduction.md`。组件通过不等于整机全网络 RTL 仿真通过。

## 6. 检测复现与上板运行

```powershell
python -B sim/reproduce_detection.py --output-dir ../repro_output/reference300
python -B board/run_desktop.py --host 192.168.10.2 --port 5001
```

第一条需参考环境，对 300 张图重新运行电脑整数参考并逐图对照保存的预测；第二条连接已运行匹配固件的板卡。批量实板对照使用 `sim/reproduce_detection.py --backend board`；完整参数、身份检查及容差见 `sim/detection_reproduction.md`。结果明确记录运行后端。

## 样例与结果口径

300 张来自原 800 张 test，使用冻结 epoch200 INT8、置信度 0.25、NMS IoU 0.45 排序：F1 降序，再按匹配框平均 IoU、平均置信度降序，最后按图片 ID 排序。清单和规则见 `data/dataset/selected_manifest.json`、`report/sample_selection.json`。这是效果优选展示子集。

原 800 张内部测试 INT8 AP50/AP50:95 为 93.6006%/74.6857%，不改写为 300 张的代表性成绩。未改模型、阈值和类别；未附其余 train/val/test 图片。历史数据接触、正常图和器件/批次独立性的限制见 `report/quality_summary.md`。

性能归档版与 SD 网络修复版 ELF 不同，2.676367 FPS 属于原性能归档版。当前Word技术文档为`report/documents/technical_document.docx`，对应PDF为`report/documents/technical_document.pdf`；从工作区最新版“技术文档.docx”和“技术文档.pdf”原样同步，包含封面和三级目录，来源与SHA见同目录`manifest.json`。历史来源快照中的旧路径用于追溯，推荐复现入口、交付状态和未覆盖范围以本文件、`report/reproduction_validation.json`、`report/missing_items.md`为准。额外硬件源码构建已按要求在布线阶段停止，未形成新bit/XSA导出或最终时序结论。
