# 自动化张量数值比对

需要对两份原始张量做浮点容差或整数数值比较时，使用 `scripts/compare_tensor.py`。该工具只读输入并输出 JSON，要求先由可信材料确认两端对应同一模型、输入、预处理和张量契约。

```text
python <skill目录>/scripts/compare_tensor.py reference.bin observed.bin --dtype f32 --byte-order little --shape 1,3 --atol 0.0001 --rtol 0.001
```

支持 `f32`、`f64`、`i8`、`u8`、`i16`、`u16`、`i32`、`u32`。形状用逗号分隔的正整数，字节序必须显式指定。容差判据为 `abs(observed-reference) <= atol + rtol*abs(reference)`。任一侧含 NaN 或 Inf 的元素一律记为不匹配，并列出非有限索引。

逻辑张量长度由 `shape × dtype` 推导。若文件尾部有存储填充，必须明确声明并验证填充值，例如：

```text
python <skill目录>/scripts/compare_tensor.py reference.bin observed.bin --dtype f32 --byte-order little --shape 1,3 --allow-padding --padding-byte 0
```

工具要求双方填充长度一致，且全部填充字节都等于声明字节；逻辑张量单独计算哈希，完整文件也另算哈希。输出包含差异元素数、最大绝对/相对误差及首个差异位置。退出码 `0` 表示声明容差内相符，`1` 表示数值差异超出容差，`2` 表示参数、文件或契约错误。

边界：工具不推断 dtype、量化尺度、布局或哪个张量才是可信参考，也不比较检测框语义；不代表模型精度、量化质量、业务验收或实板一致性通过。两端契约不匹配时，数值差异没有可比性。原始字节核对仍可使用 `compare_binary.py`。

合成示例：脚本同目录的 `test_compare_tensor.py` 覆盖容差内浮点、整数差异、显式零填充、短输入、非法形状和不符合声明的填充。


## 已有采集文件包审计

对“采集记录 + 比对记录 + 两个原始二进制”这种历史材料，运行 `scripts/audit_capture_bundle.py`。它按显式字段映射复核实际/参考文件长度与 SHA-256，并核对记录中的元素数和 float32 小端契约；可选 acceptance JSON 用来核对 checkpoint/package 身份。

```text
python <skill目录>/scripts/audit_capture_bundle.py capture_result.json comparison.json observed.bin reference.bin --acceptance-json head_acceptance.json
```

成功退出码 0，输入/来源矛盾退出码 2。输出包含四个源的重算哈希、字段映射、逻辑长度和 `reference_updated_after_capture`。适配器只接受比对材料明确声明 little-endian float32 的包；它不从文件名猜 dtype。缺参考文件时明确标记双端比较未完成；只有参考与实测双方文件均可访问且契约核对后才运行比对。不能由板端记录中的一个哈希伪装成双端比较。输出中的文件哈希是本次重算值。

此工具报告保存文件是否相同，不证明文件确属所记录运行；采集后更新参考会限制当时的parity结论，工具会保留该标记。真实历史材料的复核结果在 `examples/real_adapter/capture_audit.json`，原始样例仍在 `examples/stored_output_comparison/`。
