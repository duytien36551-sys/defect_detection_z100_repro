# Execution log

- Scope: external_detector_sources_20261025 task only; inputs and source_manifest.json; named identity-adjacent detector skills only.
- Source identity read from manifest: microsoft/onnxruntime-inference-examples at commit 16e32e87c81648773b8da2a80434a672e3b9dad6; upstream was not fetched.
- Skills actually loaded: zynq-inference-parity 1.0.0-rc1 (skill.md and references/workflow.md); detection-training-audit 1.0.0-rc1 (skill.md and references/workflow.md).
- Performed: local SHA-256/byte checks, static code-line review, PowerShell JSON parsing for the supplied annotations, and name-to-category mapping comparison.
- Not performed: Python source execution, network access, image/model download, inference, training, board operation, data modification, or prior-result/oracle review.
- Findings: intended Train2017 calibration / Val2017 evaluation; unseeded category sample; complete text mapping after aliases; provided person-only annotations have 2,693 images and no person-negative images; no runtime metrics or FP32-vs-INT8 comparison.
- Raw task, manifest, and manifest-listed input hashes were rechecked after report generation; detailed before/after values are in report.json.
