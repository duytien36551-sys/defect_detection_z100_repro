# PS 固件重建包

本目录包含 90 条 ARM GCC 编译命令及对应源文件：89 份 C 源码和启动向量汇编。模型参数、目录数据和头文件保存在包内。BSP 源码、配置和 CMake 模板位于 `build/bsp_snapshot/`，包内不提供预编译 BSP 静态库。

在包根目录检查固件与 BSP/FSBL 快照：

```powershell
python build/rebuild_firmware.py --check
python build/rebuild_bsp_sources.py --check
```

完整重建 PS ELF。需要安装与包内 ARM GCC 匹配的 Xilinx Vitis 2026.1，以及 CMake 4.0.1 和一种 CMake 构建工具（Visual Studio Build Tools 的 `nmake`、MinGW 的 `mingw32-make` 或 Ninja）。下面使用本次验证环境中的安装路径；其他队伍应替换为本机位置。输出目录必须是包外的新目录：

```powershell
New-Item -ItemType Directory -Force C:\z100_rebuild | Out-Null
python build/rebuild_firmware.py --build `
  --toolchain C:\appload\2026.1\gnu\aarch32\nt\gcc-arm-none-eabi `
  --cmake C:\appload\2026.1\tps\win64\cmake-4.0.1\bin\cmake.exe `
  --make-program C:\cbian\mingw64\bin\mingw32-make.exe `
  --generator "MinGW Makefiles" `
  --output-dir C:\z100_rebuild\baseline
```

脚本先从 BSP 快照源码生成 `libxil.a`、`libxilstandalone.a` 和 `libxiltimer.a`，再编译全部 90 个应用对象并链接 ELF。源码副本、CMake 构建目录、日志、对象、静态库、map 和 ELF 都只写入指定的包外输出目录。此流程不连接板卡或写入 SD。SD 网络修复版和 FSBL/BOOT.BIN 的入口见 `build/sd_boot/readme.md`。

2026-11-03的源码构建记录为90个对象构建完成，但新应用ELF SHA-256为`dcd2154a1041f49d7463c3f841eba83a6e814d84ef559c2ca4ed4423a135f80e`，与包内网络修复ELF`24ace234...`不相同；板端验证状态为待做。不得把新ELF当作当前已验证上板文件，也不得继承SHA为`a1fb6972...`的另一份历史性能ELF的2.676367 FPS。详细结果见[固件重建记录](../../report/reproduction_firmware.json)；BOOT.BIN组合和冷启动限制见[SD BOOT重建说明](../sd_boot/readme.md)。
