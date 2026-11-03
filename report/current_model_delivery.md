# 当前最终版模型

> 2026-11-03工程包补充：模型身份未变，另纳入独立SD网络修复v1及后续内部测试结果。原B2性能保持绑定原ELF，不向新固件继承；最新范围见 `engineering_package.md`、`quality_summary.md`。

当前最终版为 YOLOv8n PIN9 epoch200、640×640。浮点检查点 `data/pin_epoch200.pt` SHA-256 为 `2446f469d9aaf9802ad97128bd4ecd976cf1c830d374a87a1b9e76b8551663a6`；INT8 包 `data/pin_epoch200_int8.v8p` SHA-256 为 `65bb9d81aa111aa35be9ae0b2cceeb637089710e4d94d0c6acc9c65f26add13c`。

选模依据见 `model_selection.json`，完整逐类结果及统计限制见训练与量化报告。当前 B2 吞吐 2.676367 FPS，请求 P50/P95 362.644/367.810 ms；最终版数据见 `../board/evidence/final_performance.json`，原始逐帧数据见 `../board/final_run/`。

第一版 epoch108 单独作为赛事基线保存，见 `performance_baseline.md`。中间部署版本已从提交包删除。本次没有新训练、重新选模、实板或质量验收。校验以 `submission_sha256.json` 为准。
