# 真实历史训练报告适配示例

2026-11-03包内说明：此例仍是固定历史报告fixture；近期的300张精选展示集和板端运行不属于本适配器输入，也没有触发重训或重选模型。

运行位置：技能根目录。以下是本包归档的历史文件快照，路径均为本示例内的固定相对路径；它们不代表当前工程状态。

```text
python scripts/adapt_training_snapshot.py --report examples/09_training_finish200/inputs/final_report.json --acceptance examples/09_training_finish200/inputs/final_acceptance.json --split-manifest examples/09_training_finish200/inputs/split_manifest.json --results-csv examples/09_training_finish200/inputs/results.csv --output adapter-report.json
```

预期状态为 `computed_with_limitations`：按冻结报告保留 epoch 200，核对 CSV 连续轮次及最大 AP50:95 轮次，但不重新选模；生成器将两份固定工作点和类别证据适配给通用质量审计器，保留9类 AP、TP/FP/FN 与汇总计数。正常图片为0时误报率不可评估；测试、INT8和实板结果缺失时不会补零或推断。

工具重算四个输入文件的快照 SHA-256。最佳权重文件没有随示例提供，报告中的权重哈希只标记为声明值；split manifest 的哈希仅代表该清单文件，不是图像/标签数据集哈希。工具对 CSV 的最大 AP 轮次只做一致性核对，不据此改选权重。执行前后原始输入应保持不变。

此例证明适配器能读取本包已有的真实历史报告结构。它不代表本轮重训、验证集重跑或实板验收。字段映射和限制详见 自动化说明（文件：../../references/automation.md）。
