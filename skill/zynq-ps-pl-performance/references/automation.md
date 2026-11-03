# 自动化计时汇总

对单一运行中、同一计时边界采集的逐请求 CSV，使用 `scripts/summarize_timings.py` 计算描述统计：

```text
python <skill目录>/scripts/summarize_timings.py timings.csv --run-id run-2026-01 --identity model-hash/ELF-hash/board --timing-scope "request entry through response ready"
```

CSV 必须含 `duration_ms` 列，每行一个有限且非负的毫秒数值。`--run-id`、`--identity` 与 `--timing-scope` 必须显式填写；若 CSV 也有这些列，逐行必须与命令行声明完全一致，否则拒绝混合汇总。标签不在 CSV 中时，工具仍只能原样记录调用者声明，不能独立证明身份真实。输出样本数、最小值、中位数、最大值和 P50/P95。P50/P95 使用 nearest-rank：升序样本取一基排名 `ceil(p*n)` 对应值；只有一个样本时 P95 写 `null` 并明确说明样本不足以形成分布。空数据、非法数值、缺少列或空身份会报错。退出码 `0` 为汇总成功，`2` 为输入或参数错误。

样本应属于同一模型/板卡/构建、同一计时边界和同一运行组。合并不同组前先分组汇总并单独报告。单帧或 best-of-N 不能代表稳定分布；样本数很小时应明示限制。该脚本不推算 FPS、吞吐、PL 纯计算时间或模型质量，也不将 UI 停留时间识别为推理时间；计时边界由调用者负责定义和核实。

合成示例和测试见 `scripts/test_summarize_timings.py`，覆盖五样本百分位、单样本以及空、非数、负值、缺列、空身份和运行标识冲突。


## 历史 profile JSON 归一化

已有 `phase_milliseconds` 格式的单次汇总可以用 `scripts/audit_profile_json.py` 输出统一 JSON：

```text
python <skill目录>/scripts/audit_profile_json.py profile_summary.json > normalized.json
```

工具只识别 `phase_milliseconds` 的五个字段，逐项按原JSON中的毫秒数记录，保留嵌套计数器而不将其与阶段耗时相加。输出会重算所选 JSON 的 SHA，并列明 `inputs` 里只是原报告声明的路径/哈希。一个标量汇总只算一个观测样本；它是 `single_observation_total_ms`，不是P50/P95，因此两个百分位均为null；输入张数/唯一输入数只有源记录明确写出 `validation_images=1` 时才给1，否则为null。输出源哈希不能证明其中列出的旧输入文件当前仍存在或与声明相符。

命令遇到未知schema、缺少阶段字段或非法数值时以2退出。真实历史结果见 `examples/real_adapter/profile_audit.json`；本例只有单次profile，phase和嵌套计数器的含义依据源summary，不能据此声称端到端P95、持续FPS或纯PL时间。多次请求的逐样本CSV仍用本参考前面的 `summarize_timings.py`，并按运行/身份/计时边界分别统计。
