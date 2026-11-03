# SD网络修复v1交付与运行

本目录保留2026-11-03已有修复源码、构建/回归记录、实测ELF和启动镜像。`boot.bin` SHA-256为 `29c6d422cffd9e98694586312c7b8a4548ed8429b9f563498089ad636a42f5ac`，包含ELF SHA-256 `24ace23496c9e44500b83c35a59a8a6a8ca4fb0fa0c5dda7b76b9855a642cf10`，匹配epoch200模型和原100 MHz/ACP位流。

## SD操作

由实际操作者关闭板卡电源后取出SD卡，把本目录 `boot.bin` 复制到FAT32分区根目录并命名为 **BOOT.BIN**，安全弹出后插回PS Micro SD卡槽。启动拨码依厂家标识确认；现有使用记录写明BOOT_CFG两个开关均OFF。电脑地址192.168.10.1/24、板卡192.168.10.2:5001。断电后重新上电，在桌面界面检查连接并导入固定图片检测。

以上是操作说明，本次打包未操作SD或板卡。该新镜像尚无断电冷启动通过记录；旧SD热复位曾停在FSBL的PCAP等待，不能以JTAG回归代替冷启动。

## 重建与证据

本精简包保留了源码重建所需的 BSP/FSBL、应用源码与编译命令、4份修复C源码及1份头文件、Bootgen 配置，不依赖历史对象文件或静态库。以包根目录为当前目录运行 `python build/rebuild_sd_boot.py --check` 可检查重建输入身份；这只是输入检查，不会运行编译器、Bootgen 或板卡操作。完整命令和工具链要求见 `../../build/sd_boot/readme.md`。

`native_board_pool.elf` 与 `boot.bin` 是已经生成并有对应记录的上板文件。新源码构建会把 BSP/FSBL、应用对象、ELF 和 BOOT.BIN 输出到包外新目录，不覆盖这些文件。当前没有生成新的硬件 bitstream/XSA；这轮源码硬件重建已停止，状态和可用的历史硬件摘要见 `../../report/reproduction_hardware.md` 与 `../../report/final_hardware/synthesis_implementation_summary.md`。硬件重建状态不改变这里现存最终上板文件的身份。

`src/`为5份修改源码/头文件；`evidence/`为原回归记录；`native_board_pool.elf`为已有实测ELF。`readme.md`介绍当前交付，`rebuild.py`是`build/rebuild_sd_boot.py`的兼容入口。`build_manifest.json`保留历史编译来源，并由可迁移构建入口读取和重写路径。`sd_usage_original.md`与`sd_verification_original.json`为历史来源快照，实际操作以本文件为准。

原性能归档版ELF为 `board/artifacts/native_board_pool.elf`，与本目录ELF不同；2.676367 FPS属于原性能归档版。本修复版另有 2026-11-03 JTAG + 已获资格的 SCOPED 缓存模式记录：30 次同图请求全部与参考一致，p50 362.421 ms、P95 364.628 ms，批次 2.767125 FPS；两图 ABABA 五帧原始检测头与参考逐字节一致。证据见 `../evidence/pc_fast_20261103/runtime_identity.json`。这依赖外部 JTAG 启动/资格交接，不是本 SD 镜像的冷启动成绩；普通启动默认 FULL 缓存维护，不能只凭 ELF/BOOT 相同承诺该速度。有限重复记录不代表长期稳定性或数据集实板精度验收。
