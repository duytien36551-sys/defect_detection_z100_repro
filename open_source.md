# 赛题开源发布说明

本发布版响应赛题第 3.3.3.3 节：在 GitHub 或 Gitee 开源，并采用允许再分发的开源协议，推荐 MIT 或 Apache-2.0。

- 仓库：<https://github.com/duytien36551-sys/defect_detection_z100_repro>。
- 公开范围：Public，供未登录用户浏览、克隆及下载。
- 贡献者有权授权的原创源码采用 [MIT](license)，允许复制、修改和再分发，需保留版权及许可声明。
- 第三方代码、依赖、模型和数据继续适用原条款，见 [第三方许可说明](third_party_notices.md)。
- 构建与复现命令见 [首页](readme.md)，正式技术文档见 [PDF](report/documents/technical_document.pdf) 和 [Word](report/documents/technical_document.docx)。

## 与原工程包的关系

初始提交 b2f86ccfcc3686450b7f307b426a0fa3709fa4f2 保存首次上传的 5224 个文件。2026-11-04 本次同步以本地最新版工程包的 5273 个文件为基础，包含最新 29 页 Word/PDF、七项技能及相关说明；另保留 MIT、第三方许可证和公开发布入口。只有首页、开源发布说明、文件清单和 SHA-256 因公开发布需要调整，其余工程包文件均与本地最新版逐字节一致。原桌面工程包没有被本次 GitHub 同步修改。

本次发布没有启动训练、Vivado、编译、推理或实板操作。公开和许可不表示其他赛题技术指标、数据来源授权或待验收事项已经通过。

## 下载和检查

在仓库页面选择 Code → Download ZIP，解压后执行：

```text
python -B sim/verify_submission.py
python -B sim/verify_model.py
```

也可克隆：

```text
git clone https://github.com/duytien36551-sys/defect_detection_z100_repro.git
```

克隆生成的 .git 属于本地管理数据，旧版 verify_submission.py 会将其视作额外内容。完整性检查请在 Download ZIP 解压目录或 git archive 导出的源码目录执行。
