# DMA事件时间线只读整理

`scripts/audit_dma_timeline.py` 读取显式 UTF-8 JSON 事件文件，按 `run_id` 分组并保留各组的原始记录顺序，标记时间戳倒退、多个运行ID和交错运行。它不探测硬件、不解释寄存器位、不推断根因。

输入为 `{"schema_version":1,"events":[...]}`，且至少包含一个事件。每项需要非空字符串 `run_id`、`timestamp`、`event`；时间戳须为带时区的 ISO-8601 字符串。其他字段会原样保留，例如序号、方向、长度和TLAST状态。缺少的字段保持缺失，脚本不会补造。

```text
python scripts/audit_dma_timeline.py examples/dma_events_synthetic.json
```

退出码：0 表示输入只包含一个运行ID且记录顺序的时间戳不倒退；1 表示多个运行ID或存在倒序，需回看证据；2 表示文件、JSON或字段格式错误。`A,A,B,B` 是两个连续运行块，标记为多个运行，但不标记为交错；`A,B,A` 才标记为交错。对于交错运行，报告按运行ID分组展示，并标明输入索引以便追溯；请勿把跨运行记录拼成一次DMA事务。

示例数据为合成记录。日志中的时间顺序只能说明被记录事件的顺序，无法证明未采集到的硬件波形或DMA内部状态。解释寄存器需另有匹配板卡、IP版本和寄存器定义作为依据。


# 本项目验收记录适配

`scripts/adapt_acceptance_runs.py <材料目录>` 只对任务界定的日志/验收材料子目录运行，切勿扫描整个多GB工程；输出路径必须在扫描目录之外。脚本递归发现 `*_acceptance.json`，读取实际出现的开始/结束时间、逐请求事件、状态、模型哈希和类别哈希。为 `batch_acceptance.json` 附带解析同目录 `batch_log.log` 与 `requests.jsonl`；失败/诊断验收 JSON 按文件名前缀寻找对应 `*_run.log`。报告为每个原始 JSON 与伴随文件计算 SHA-256。日志中没有结构化时间戳时，只记录行号和原文行，绝不伪造时间并混入带时区时间线。

```text
python scripts/adapt_acceptance_runs.py examples/08_dma_cross_run_failure/inputs --output dma_audit.json
```

空请求表、请求摘要计数与明细数冲突、缺少带时区的逐请求时间戳时会列出缺项并要求复核；不产生“单次时间线完整”的结论。发现多个验收文件时状态为 `review_required`，表示必须分别查看各次运行；全局排序只依据各原记录的带时区时间戳，不推断故障因果、寄存器位语义、TLAST或根因。状态1表示多运行/需审阅或时间异常，0表示单运行材料提取完成，2表示输入/schema错误。历史案例生成报告见 `examples/real_adapter/dma_from_case_08.json`；文件名“later”中的诊断运行时间实际早于失败运行，报告保留时间证据，不能据名称重排。
