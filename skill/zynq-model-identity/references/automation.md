# 身份清单只读核验

`scripts/audit_identity.py` 从显式 JSON 清单读取相对文件路径，对列出的本地文件重新计算 SHA-256，并对照清单中的可选声明值。它不会扫描工程、访问板卡或证明某文件确实参与了目标运行。

输入为 UTF-8 JSON：`{"schema_version":1,"artifacts":[...]}`。清单须至少列出一项，且规范化后不能有重名项。每项需要非空字符串 `name`、相对 `path`；`required` 可选且默认为 `true`；`declared_sha256` 可选，提供时必须是64位十六进制。路径必须留在清单所在目录树内。绝对路径和越界路径会拒绝。提供声明哈希时，文件项状态为 `match` 或 `mismatch`；没有声明哈希时状态为 `hashed_only`，表示只重算哈希，不能宣称匹配。

从该技能目录运行：

```text
python scripts/audit_identity.py examples/identity_manifest.json
```

退出码：0 完整且声明匹配；1 至少一个哈希不匹配；2 输入、JSON 或路径无效；3 有必需文件缺失。可选文件缺失会列为 missing，但不单独导致 incomplete。输出 JSON 会标明重算哈希和边界。

示例清单中的文件内容为合成数据，不能作为真实模型、ELF 或 bitstream 身份证据。哈希相等只说明当前列出的文件字节相同，运行身份仍需运行记录或设备回读支持。


# 现有构建材料适配

`scripts/adapt_build_materials.py <工程或材料目录>` 只对用户或任务已界定的材料子目录运行，切勿把大型仓库根目录作为扫描范围；脚本递归发现文件名严格为 `build_manifest.json` 与 `build_report.json` 的 UTF-8 JSON，识别该项目已出现的 `model_sha256`、`source_sha256`、`elf_sha256`、`package_sha256` 和 `files.*.sha256` 字段；对扫描目录内实际存在的文件重新计算 SHA-256。路径按清单所在目录解释，缺失时保留“仅有声明”并列出缺项。

```text
python scripts/adapt_build_materials.py examples/01_identity_normal/inputs --output identity_audit.json
```

输出文件必须写在扫描目录外，避免覆盖输入或扫描结果自包含。空对象或没有已支持身份/哈希字段的报告会标为 `unsupported`，防止无证据报绿。状态 `checked` 表示所有发现的声明文件可核对，`incomplete` 表示清单声明了未随目录提供的文件，`conflict` 表示可重算哈希与声明不同。工具不解压XSA/bitstream、不猜未知 JSON schema、不认定运行时加载身份。原始案例目录只读。真实历史样本生成报告见 `examples/real_adapter/identity_from_case_01.json`；其 `incomplete` 结果反映示例仅保留了清单/报告，没有包含构建二进制或源代码。
