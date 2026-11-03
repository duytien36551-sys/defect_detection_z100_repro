# 赛题开源发布说明

本发布版响应赛题第 3.3.3.3 节：在 GitHub 或 Gitee 开源，并采用允许再分发的开源协议，推荐 MIT 或 Apache-2.0。

- 仓库：<https://github.com/duytien36551-sys/defect_detection_z100_repro>。
- 公开范围：Public，供未登录用户浏览、克隆及下载。
- 贡献者有权授权的原创源码采用 [MIT](license)，允许复制、修改和再分发，需保留版权及许可声明。
- 第三方代码、依赖、模型和数据继续适用原条款，见 [第三方许可说明](third_party_notices.md)。
- 构建与复现命令见 [首页](readme.md)，正式技术文档见 [PDF](report/documents/technical_document.pdf) 和 [Word](report/documents/technical_document.docx)。

## 与原工程包的关系

初始提交 b2f86ccfcc3686450b7f307b426a0fa3709fa4f2 保存原工程包全部 5224 个文件。后续发布提交只补充许可、发布说明及首页入口，并更新文件清单和 SHA-256；硬件、固件、模型、数据及历史测试结果保持原字节。原桌面工程包没有被覆盖。

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
