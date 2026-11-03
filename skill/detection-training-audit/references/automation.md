# 质量报告自动审计工具

`scripts/audit_quality_report.py` 对显式 JSON 文件执行只读结构和算术检查。它不读取训练数据、不访问模型文件、不重选模型，也不运行训练或推理。

运行示例：

```text
python <本技能绝对路径>/scripts/audit_quality_report.py <报告.json>
python <本技能绝对路径>/scripts/audit_quality_report.py <报告.json> --output <审计结果.json>
```

完整可运行输入见 `examples/quality_report_audit.json`。命令返回码为 0 表示通过本工具的结构/算术检查，1 表示报告不完整或存在审计问题，2 表示输入/输出文件读写失败或输入无法解析。输出路径解析后若与输入路径相同，工具会拒绝写入，避免覆盖原报告。`audit_pass` 只说明通过下述检查，不代表业务门槛通过。

## 输入字段

顶层必须含 `schema_version: 1`、非空 `required_classes` 和 `evaluations`。每项 evaluation 必须含唯一 `id`，以及 `split`、`backend`、`model_sha256`、`source_weight_sha256`、`dataset_sha256`、`protocol_id`、`images`、`normal_images`、`classes`。三个 SHA-256 必须为64位十六进制字符串；哈希和协议标识由报告提供，此工具不会打开路径重算哈希。

每个类别行需要 `name`、非负整数 `targets`、`tp`、`fp`、`fn`，以及0到1之间的 `ap50`、`ap50_95`。类别名须与 `required_classes` 完全一致。TP、FP、FN由提交者按固定工作点评价协议产生；该工具不实现IoU匹配或检测器。

`normal_images` 为0时，正常图误报率字段输出为 `null` 并标记不可评估；大于0时必须提供不超过该值的 `false_positive_normal_images`，工具计算 `false_positive_normal_images / normal_images`。工具按 `split`、`backend` 和 evaluation ID 保留记录边界，并分别汇总每项 evaluation 的固定工作点微平均 Precision、Recall、F1 和 TP/FP/FN，不跨后端或数据集合汇总。零检测时 Precision 的分母为0，结果为 `null`。

可选的 `quantization_comparison` 指定不同的 `float_evaluation_id` 与 `quantized_evaluation_id`。前者 `backend` 必须是 `float`/`float32`/`fp32`，后者须是 `int8`/`int8-reference`/`quantized`/`quantized-int8`。只有双方有效且一致的 `source_weight_sha256`、`dataset_sha256`、`protocol_id`、`split` 才计算 `(float AP50:95 - quantized AP50:95) × 100` 个百分点。两种后端的 `model_sha256` 可以不同。身份/协议不同或无效时跳过量化差计算并给出警告或审计问题。

## 边界

缺少必需类别、计数类型错误、负数、计数关系矛盾或AP越界都会阻止 `audit_pass`。缺少量化对比不影响结构检查，但工具不会据此宣称量化通过。类别统计中的 `tp + fn = targets` 是本输入格式的完整性约束；特殊忽略标注/被排除目标需要先按协议明确另行表达，不能强塞进此格式。

本工具检查报告结构与可重算的算术关系，不证明数据划分真实独立、权重身份声明真实、AP来源正确、报告没有泄漏测试集选模、实际板端运行或业务验收。请将输出与原始清单、日志、权重和评价协议交叉核验。

## 适配已归档训练快照

`scripts/adapt_training_snapshot.py` 可读取本项目中与其结构相同的训练快照：`final_report.json`、`final_acceptance.json`、`split_manifest.json` 和训练 `results.csv`。它把已报告的逐类 AP 与固定工作点计数映射到上述质量审计格式，同时核对 CSV 轮次是否连续、CSV 最大验证 AP50:95 所在轮次是否与报告声明的最佳轮次一致，以及验收记录中的权重哈希/轮次声明是否一致。

```text
python <skill目录>/scripts/adapt_training_snapshot.py --report final_report.json --acceptance final_acceptance.json --split-manifest split_manifest.json --results-csv results.csv --output audit.json
```

包内历史文件可直接运行，详见 `examples/real_adapter/readme.md`（文件：../examples/real_adapter/readme.md）。适配器只核对既有选择声明，不重新选权重。返回码 `0` 表示适配成功且没有发现源记录一致性冲突，`1` 表示发现轮次/身份/轮次记录冲突，`2` 表示输入无法解析或格式无效。输出 `computed_with_limitations` 表示产生了结构化审计结果，并非模型或业务通过；内部质量报告若有缺项会保留 `incomplete` 状态。

每个输入都会记录当次文件 SHA-256。最佳权重未随快照提供时，其哈希仍是原报告声明，不能视作本工具重算。split manifest 的文件哈希只标识清单快照，不是底层图像或标签数据集哈希。协议指纹仅覆盖报告中已有的推理设置和固定工作点字段。CSV 的最大 AP 只用于与原声明交叉检查；若不一致，工具报告冲突，不会代替原冻结规则选出新权重。

该适配器有意只映射一个明确的冻结验证结果。原验证集子集、测试集、INT8、实板和业务门槛不混在同一汇总项中；原始报告中没有的后端或集合仍作为缺项披露。固定阈值的 TP/FP/FN 算术重算结果与训练 CSV 中自动工作点的 Precision/Recall 不混用。`normal_images=0` 时正常图误报率不可评估。该示例证明适配器可以消费已归档的真实项目文件结构，不代表本次重跑训练、模型推理或实板评测。
