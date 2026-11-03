# SD 网络修复最终交付

本目录保留原交付的网络修复 ELF、BOOT.BIN、修复源码和身份记录：应用ELF SHA-256为`24ace23496c9e44500b83c35a59a8a6a8ca4fb0fa0c5dda7b76b9855a642cf10`，BOOT.BIN SHA-256为`29c6d422cffd9e98694586312c7b8a4548ed8429b9f563498089ad636a42f5ac`。包内既有JTAG回归使用默认FULL缓存策略；它没有验证新BOOT.BIN的SD冷启动。

2026-11-03工作区侧另有scoped-mode JTAG补充记录，匹配本ELF、epoch200模型SHA-256`65bb9d81...`和bitstream SHA-256`9250f988...`。同一准备输入连续30次请求全部参考一致、自动重试为0，P50/P95为362.42065/364.6278 ms，批次吞吐2.767125 FPS；这不表示默认FULL达到该时延，也不能将差异归因于ELF本身。五份ABABA原始检测头各613200字节，均逐字节匹配对应参考。运行身份、30次请求和ABABA摘要副本已收入[板端证据目录](../evidence/pc_fast_20261103/runtime_identity.json)、[连续请求记录](../evidence/pc_fast_20261103/continuous30.json)和[原始头摘要](../evidence/pc_fast_20261103/raw_parity_summary.json)。包内只有结果记录；启动仍依赖未随包提供的`.codex/restore_pc_scoped.tcl`及其相关外部文件，不能据此声称包可自包含地复现scoped启动。SD冷启动和SD启动下的scoped模式均未验证。

2026-11-03已记录的源码构建另行生成ELF SHA-256`dcd2154a...`和BOOT.BIN SHA-256`586d7bd1...`，均不同于本目录原上板文件；构建记录状态为`BOOTGEN_COMPLETE_BOARD_PENDING`，板端验证未运行。可迁移重建入口为包根目录的`build/rebuild_sd_boot.py`，步骤和FSBL/bitstream选择参数见[SD BOOT重建说明](../../build/sd_boot/readme.md)。对象、BSP库、FSBL、ELF、日志和BOOT.BIN输出到包外新目录；原上板文件不会被覆盖。新镜像仍需在目标板完成SD冷启动验收。原始使用边界见[SD使用说明](usage.md)。
