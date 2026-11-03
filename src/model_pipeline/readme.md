# PIN640模型导出、量化与离线评估源码

工程包上下文（2026-11-03）：当前部署身份为epoch200、PIN九类、640输入。精选300张仅是展示样例，不是代表性或独立测试集。

`deployment/candidates/pin640/`保留原程序的相对层级，使 `evaluate_deployment.py` 对上级 `unified_metrics.py` 的导入关系不变。包含export_graph、quantize、pack_model、prepare_deployment、evaluate_deployment和reference/v8_decode实现，均为既有源码快照。

同层 `firmware/`、`tests/`保留PIN640通用C整数参考/协议及主机回归源码（decode_parity、runtime_graph、runtime_guards、service_guards、network_stream等）。它们是参考与回归材料，不能替代 `src/ps/current_compiled/` 的最终native/ACP固件快照，也不代表完整当前RTL平台仿真。原测试构建入口依赖生成模型头和当时目录，迁移后尚未重新编译运行。

浮点图、权重和导出检查见 `data/float_export/`；冻结PT为`data/pin_epoch200.pt`，V8P为`data/pin_epoch200_int8.v8p`；当前INT8权重统一为`data/quantization/weights_int8.npz`，部署元数据见`data/model/`；数据来源审计见 `data/provenance/`。相同字节的副本已合并，位置映射见`data/deduplication_manifest.json`。运行前按 `build/requirements_model_snapshot.txt`在独立环境准备依赖，具体参数可阅读各脚本的argparse定义。

`evaluate_deployment.py`增加可选`--checkpoint`，用于模型权重独立存储的布局；使用本包浮点导出时，参数对应为`--model data/float_export --checkpoint data/pin_epoch200.pt --quant data/quantization`，其余数据清单、域及包外输出参数按任务提供。未指定该参数时仍使用原来的`<model>/source.pt`。本次仅调整文件位置选择，未修改推理计算或重新执行评估。

`historical_test_once.py`、`historical_validation.py`是既有评估执行脚本的原样快照，包含当时目录布局和冻结路径；不是迁移后可直接运行的一键入口。`prepare_deployment.py`要求输出位于它的源码目录下，不要在已封存的本包直接生成结果；复现时复制源码到独立工作目录，再使用显式checkpoint/model/quant/manifest/output参数。标准输出、结果和源身份须另行保存。

推荐检测复现入口为包根的`sim/reproduce_detection.py`，使用本目录整数图/解码实现及包内冻结参数。`report/reproduction_detection.json`记录此前对精选300张的电脑整数参考重跑及离线预测对照；该结果是固定模型输出复现，不是代表性精度指标，也不是本次2026-11-03打包期间的新推理。为避免导入整数参考时在封存源码内建立`.config`，`export_graph.py`移除了原有模块导入时创建配置目录的两行，计算实现未变。本轮未重新导出、校准、量化或训练。历史完整测试报告在`report/test_evaluation/`，量化报告在`report/int8_validation.json`，它们不代表完整实板精度。
