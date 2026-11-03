# 外部pynq项目复用记录

来源、固定提交、逐文件URL和SHA-256见source_manifest.json（文件：external_source_manifest.json）。本目录只分发原创审查记录及来源索引，不分发外部源码、notebook图片或数据标注。

复现：按清单URL取得每个文件，保持path相对结构并核对SHA-256和字节数；将下载目录交给Codex，先依据自然语言任务选择技能，读取相应skill.md及references/workflow.md，形成自己的报告，再与独立报告（文件：external_report.md）核对。该任务只读，不执行下载的仓库代码。

审查任务：核对平台和接口身份、PS/PL数据流、DMA契约及notebook所存计时的证据范围。

报告只支持静态材料审查能力，不代表实际部署、目标板兼容、模型精度或通用PYNQ实测。源代码行号对应清单中的固定提交，不能直接套用到新版本。
