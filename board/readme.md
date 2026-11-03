# 最终上板文件与界面

包内保留两套身份不同的上板应用及对应资料：`artifacts/native_board_pool.elf`属于原性能归档版；`sd_network_fix_v1/native_board_pool.elf`和`sd_network_fix_v1/boot.bin`属于独立网络修复版。另有原交付的`artifacts/fsbl.elf`、`artifacts/z100_platform.bit`和`artifacts/z100_platform.xsa`。历史持续吞吐2.676367 FPS绑定SHA-256为`a1fb6972...`的性能归档ELF，不能记到网络修复ELF或后续源码重建ELF名下。

2026-11-03工作区侧补充了一次scoped-mode JTAG记录：应用ELF SHA-256为`24ace234...`、模型为`65bb9d81...`、bitstream为`9250f988...`。对同一张准备好的输入连续请求30次，30次均与参考输出一致且没有自动重试；`BoardClient.infer`范围的P50/P95为362.42065/364.6278 ms，最小/最大为344.3134/365.0585 ms，批次吞吐2.767125 FPS。工作区补充记录的结果副本现随包保存在[运行身份](evidence/pc_fast_20261103/runtime_identity.json)、[30次请求摘要](evidence/pc_fast_20261103/continuous30.json)和[ABABA原始头对照](evidence/pc_fast_20261103/raw_parity_summary.json)；后者记录5份613200字节输出均与对应参考逐字节一致。包内只有结果记录；启动它们所用的`.codex/restore_pc_scoped.tcl`及其外部文件不随包提供，因此当前包不能独立复现该scoped启动过程。

上述scoped结果只描述该JTAG启动范围，不代表默认FULL运行表现，也不能单凭ELF身份推导性能提升。默认FULL完整路径仍约为500 ms以上。新源码构建生成的ELF和BOOT.BIN与包内上板参考不同，尚未上板验证；SD冷启动和SD启动下的scoped模式均未验收。修复版原有JTAG回归和SD使用边界见[网络修复版说明](sd_network_fix_v1/readme.md)及[SD使用说明](sd_network_fix_v1/usage.md)。

从包根目录可运行`python -B board/run_desktop.py --check`，只离线检查epoch200模型和类别身份，不开窗口、不访问网络。连接匹配固件的板卡时运行`python -B board/run_desktop.py --host 192.168.10.2 --port 5001`；该入口不烧录、不复位，GUI历史默认写在包外`../repro_output/desktop_history`，也可用`--history-dir`指定其他包外目录。Windows可用[启动脚本](start_desktop.bat)；如需完整桌面依赖，按[桌面依赖清单](../build/requirements_desktop.txt)安装。包内300张筛选样本的参考和板端批量对照命令见[检测复现说明](../sim/detection_reproduction.md)。
