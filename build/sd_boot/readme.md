# SD BOOT 重建

此入口从 `build/bsp_snapshot/` 源码构建 BSP 静态库和 FSBL，编译全部 90 个应用对象、覆盖 4 个网络修复对象、链接 ELF，再调用 Xilinx Bootgen。原上板 FSBL、bit、ELF 和 BOOT.BIN 留作身份参考，不会被重建输出覆盖。

完整构建同时是 FSBL 源码重建入口；FSBL 源码来自 `build/bsp_snapshot/zynq_fsbl/`，生成的 FSBL ELF 和 BSP 库写入包外输出目录。快照的 `RSA_SUPPORT` 未启用且包内不含 SDK 专有的 `librsa.a`，构建器只在包外源码副本中跳过未使用的 `xilrsa` 目标和链接依赖，并在检测到 RSA 启用时停止配置。建议使用 Vitis 2026.1 ARM GCC 13.4.0、CMake 4.0.1、MinGW Make 4.4.1 和 Vitis 2026.1 Bootgen。Bootgen 参数应指向 Vitis 的 `bootgen.bat` 启动器；它会设置运行时环境并记录启动器路径和哈希。下面给出本次验证使用的路径，其他队伍需替换为本机安装位置。

在包根目录检查重建闭包：

```powershell
python build/rebuild_sd_boot.py --check
```

实际重建命令示例：

```powershell
New-Item -ItemType Directory -Force C:\z100_rebuild | Out-Null
python build/rebuild_sd_boot.py --build `
  --toolchain C:\appload\2026.1\gnu\aarch32\nt\gcc-arm-none-eabi `
  --cmake C:\appload\2026.1\tps\win64\cmake-4.0.1\bin\cmake.exe `
  --make-program C:\cbian\mingw64\bin\mingw32-make.exe `
  --generator "MinGW Makefiles" `
  --bootgen C:\appload\2026.1\Vitis\bin\bootgen.bat `
  --output-dir C:\z100_rebuild\sd_network_fix
```

默认 BOOT 输入是本次源码构建的 FSBL 和包内参考 bitstream。指定另一版 FSBL 或新硬件构建的 bitstream 时，追加 `--fsbl <fsbl.elf>`、`--bitstream <z100_platform.bit>`；脚本仍会构建并记录源码版 FSBL。对象、源码工作副本、静态库、CMake 构建文件、日志、ELF、map、BIF 和 BOOT.BIN 均写在包外新目录。ARM GCC/CMake 阶段使用固件构建互斥锁，Bootgen 阶段使用共享 Xilinx 工具锁并检查相关进程空闲。不访问板卡或写 SD；生成镜像后仍需单独执行目标板 SD 冷启动验收。

共享 Xilinx 工具锁忙时，可先用 `--defer-bootgen` 完成 BSP、FSBL 和应用 ELF 构建，并在同一外部目录保存 BOOT 输入。锁释放后，用同一输出目录单独续跑 Bootgen：

```powershell
python build/rebuild_sd_boot.py --bootgen-only `
  --bootgen C:\appload\2026.1\Vitis\bin\bootgen.bat `
  --output-dir C:\z100_rebuild\sd_network_fix
```

如果完整 `--build` 在 Bootgen 锁处返回 `BOOTGEN_PENDING_LOCK_BUSY` 或 `BOOTGEN_PENDING_TOOL_BUSY`，也可用上述命令从保留的结果续跑。

如果新的硬件流程已经生成 bitstream，而应用 ELF 和 FSBL 不需要重编，可从已验证的外部构建复制 ELF、FSBL、BIF，并在新目录中组合该 bitstream。源构建可为成功、等待 Bootgen 或 Bootgen 失败但 ELF 已完成的结果；脚本会先校验源结果记录的 ELF、FSBL、原 bitstream 和 BIF 哈希。目标目录必须是包外的新目录，原构建不会被覆盖。示例：

```powershell
python build/rebuild_sd_boot.py --bootgen-only `
  --reuse-build C:\z100_rebuild\sd_network_fix `
  --bitstream C:\z100_hardware\z100_platform.bit `
  --bootgen C:\appload\2026.1\Vitis\bin\bootgen.bat `
  --output-dir C:\z100_rebuild\source_chain_boot
```

该模式不运行 GCC、CMake 或 Make；它只复制并校验已有 ELF/FSBL/BIF、复制所选 bitstream，再调用 Bootgen 生成新 BOOT.BIN。目标目录必须不存在。若共享 Xilinx 工具锁忙，已准备好的新目录会保留为待续跑状态，可对该新目录再次运行 `--bootgen-only --bootgen <bootgen.bat> --output-dir <source_chain_boot>`。

2026-11-03已记录的完整固件构建使用包内参考bitstream `9250f988...`生成新ELF和BOOT.BIN，结果分别为`dcd2154a...`和`586d7bd1...`；它们与目录中原上板ELF/BOOT.BIN不同，报告状态为`BOOTGEN_COMPLETE_BOARD_PENDING`，`board_validation`为`NOT_RUN`。因此这证明了源码构建和Bootgen产物生成，不证明新ELF/BOOT.BIN已在板上启动；SD卡冷启动仍未验证。详情见[固件重建记录](../../report/reproduction_firmware.json)。新硬件源码流程没有导出可供本次组合的bitstream，状态见[硬件重建报告](../../report/reproduction_hardware.md)。
