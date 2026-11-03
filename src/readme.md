# 最终版源码

工程包上下文（2026-11-03）：当前部署身份为epoch200、PIN九类、640输入；模型头文件和桌面客户端均属于本包源码。

`model_pipeline/`保存PIN640的导出、量化、打包及离线评价源码；`training/`保留训练辅助实现，训练脚本及摘要在`report/training_archive/`，原始运行日志已排除。网络修复版的5份修改源码独立放在`board/sd_network_fix_v1/src/`，不覆盖性能归档版源码快照。

`rtl/current/` 保存最终平台 RTL 与 ROM；`ps/current_compiled/` 保存实际编译的 PS 源码；`model/` 为 epoch200 模型头文件；`desktop/` 为电脑界面。桌面依赖列于 `build/requirements_desktop.txt`；从包根可运行 `board/start_desktop.bat` 或 `python -B board/run_desktop.py` 启动。界面连接已启动且匹配的板端服务，启动器只检查模型包身份并打开界面，不负责加载、烧写或启动板卡。离线 `--check` 仅核对模型配置。构建材料检查入口见 `build/`。

当前复现入口见根readme.md。`board/baseline/`仅保留第一版历史摘要/参考；旧epoch108模型数据和旧版bit/ELF/XSA未作为当前交付产物附带。
