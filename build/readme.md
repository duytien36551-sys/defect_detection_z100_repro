# 构建与重建入口

所有命令均从工程包根目录运行。默认`--check`只核对包内输入身份，不会启动编译器、Vivado或Bootgen；完整工具链、参数和输出目录要求分别见[硬件源码重建](hardware_source/readme.md)、[PS固件重建](firmware_portable/readme.md)和[SD BOOT重建](sd_boot/readme.md)。

- 硬件源码检查与重建：`python build/rebuild_hardware_source.py --check`；完整构建使用 `--build` 和本机 Vivado 2026.1，输入为包内 RTL/ROM、PS block design 及约束。无需历史 DCP。
- PS 固件检查与重建：`python build/rebuild_firmware.py --check`；完整构建从包内 BSP 源码、配置和应用源码生成库、对象及 ELF。
- SD 网络修复版检查与重建：`python build/rebuild_sd_boot.py --check`；完整构建会重建 BSP/FSBL、90 个应用对象和 ELF，并由 Bootgen 生成 BOOT.BIN。它使用包内历史 bitstream 作为默认 BOOT 输入；如需组合新 bitstream，按 `sd_boot/readme.md` 提供该输入。

完整构建的对象、静态库、日志、检查点及新 ELF/bit/BOOT.BIN 均写入包外指定的新目录。包内 `../board/artifacts/` 与 `../board/sd_network_fix_v1/` 中的最终上板文件作为交付和身份参考保留，不由构建入口覆盖。构建本身不访问板卡、不写 SD 卡，也不能代替实板启动验收。

# 2026-11-03状态与历史报告

硬件源码重建按用户要求在最终布线验收和bit/XSA导出前停止；没有形成新的最终硬件文件或上板结果。状态见[硬件重建报告](../report/reproduction_hardware.md)；[既有综合/实现摘要](../report/final_hardware/synthesis_implementation_summary.md)对应包内历史平台产物，不是新源码构建结果。

记录中的PS固件源码构建已完成Bootgen，但板端验证待做；生成的ELF和BOOT.BIN均不同于包内网络修复版身份，且使用的是包内参考bitstream。构建哈希和范围见[固件重建结果](../report/reproduction_firmware.json)及[执行范围记录](../report/reproduction_validation.json)。既有9项RTL组件/核心回归和300张CPU整数参考检测分别见[RTL结果](../report/reproduction_rtl.json)与[检测结果](../report/reproduction_detection.json)，它们是独立的既有报告，不是整网RTL推理或2026-11-03更新工程包时重跑的结果。

运行 `python -B build/prepare_dataset.py` 核对保留的 300 组图片/标签；该脚本无需 `--check` 参数。上述重建入口的 `--check` 只验证输入清单及哈希，不等于构建通过；完整构建需复现者安装相应 Xilinx 工具链，并显式使用 `--build`。

当前技术文档副本位于[28页DOCX](../report/documents/technical_document.docx)和[28页PDF](../report/documents/technical_document.pdf)，来源、大小与SHA-256记录在[文档元数据清单](../report/documents/manifest.json)。
