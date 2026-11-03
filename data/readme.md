# 数据与模型

交付上下文（2026-11-03）：冻结部署候选为epoch200、PIN九类、640输入；此处300张仍只作精选展示样例。

本版仅含 `dataset/images/test/` 中300张效果优选图片，以及 `dataset/labels/test/` 中300份标签。`dataset/test.txt`是完整交付图片清单；不附train/val图片或额外test图片。筛选来自原800张test，固定模型与阈值，规则和逐图分数见 `../report/sample_selection.json`。此子集用于展示，不是代表性测试集。

保留epoch200 PT、INT8 V8P、浮点导出/量化参数与参考数据；模型身份未改变。`provenance/canonical_manifest.json`是冻结量化校准身份所需的原8000条元数据，不代表附带8000张图片；`source_label_audit.json`仅保留这300张的审计行。元数据中的原路径用于溯源。

已移出旧epoch108数据并合并字节完全相同的模型副本。当前PT统一为`pin_epoch200.pt`，浮点权重为`float_export/weights_float.npz`，当前INT8权重为`quantization/weights_int8.npz`；旧位置到保留位置的对应和SHA见`deduplication_manifest.json`。`model/export_snapshot/`保留历史导出元数据及不同字节版本的量化快照，不是独立的完整模型目录。所移出的文件不随工程包交付。

执行 `python -B build/prepare_dataset.py` 核对300组图片/标签及SHA。来源授权、物理器件独立性和历史训练接触的限制仍存在，未生成新的实板精度结论。
