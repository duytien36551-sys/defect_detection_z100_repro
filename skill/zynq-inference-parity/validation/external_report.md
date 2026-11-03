# 外部检测项目静态审查

**结论：** 源码展示了一个 COCO Train2017 校准、Val2017 评估的 TensorRT INT8/FP16 配方，也提供了可静态验证的 80 类名称映射。但没有模型、运行预测或精度日志，因此没有 AP、固定阈值 P/R、量化损失或板端结果可报告。所附标注仅包含 person 类：2,693 张图、11,004 个目标，且每张图都包含 person；正常图误报率不可评估。

## 范围与来源

仅审查任务指定的 task.md、source_manifest.json、其 inputs/ 清单文件，以及 zynq-inference-parity 与 detection-training-audit 的 skill.md 和 references/workflow.md。manifest 将来源固定为 microsoft/onnxruntime-inference-examples commit 16e32e87c81648773b8da2a80434a672e3b9dad6，检索时间记录为 2026-10-25T15:46:32.380572+08:00。未联网确认上游版本。

未执行随附 Python 源码，未下载模型或图像，未运行推理、训练或板卡；只使用 PowerShell 静态查看源码、计算 SHA-256，并解析随附 JSON 标注。

## 标注统计

| 指标 | 本次计算 |
|---|---:|
| 图片记录 / 唯一 image_id | 2,693 / 2,693 |
| 标注记录 / 唯一 annotation_id | 11,004 / 11,004 |
| 类别 | 1：person（COCO category_id=1） |
| person 目标数 | 11,004（其中 iscrowd=1 为 227） |
| 至少一个 person 标注的图片 | 2,693 |
| 无 person 标注的图片（仅在所附子集中） | 0 |
| 缺失 image 引用 / 无效 bbox / 重复 image_id / 重复 annotation_id | 均为 0 |

这是一份 person-only 子集；没有 person-negative 图片，故正常图误报率不可评估，不能记作 0%。其他 79 类在该标注文件中没有记录，报告为“未覆盖”，不当作测得 0 个目标。

## 校准/验证隔离

示例文档和主分支分别把 COCO 2017 Train 图像用于 calibration，把 COCO 2017 Val 图像用于评价（e2e_user_yolov3_example.py:L151-L170、L181-L189）。这是源码中的预期划分；材料没有实际校准/验证文件清单、图像哈希或 ID 交集报告，因此实际隔离尚未核实。

coco_filter.py 在每个类别的图片 ID 中调用无固定随机种子的 random.shuffle，再最多取前 20 个并做集合并集，随后从 coco_url 下载图像到 calib 目录（L99-L116）。以 80 类计，代码上界为 1,600 个唯一校准图像；实际数量取决于类别覆盖和跨类重叠，随附材料没有已生成 ID 列表、图像或校准表。未固定采样 seed 会使校准样本难以复现。源码还按 os.listdir 顺序分片，未排序或固化文件列表。

## 类别映射

onnx_coco_classes.txt 有 80 个输出类名，coco-object-categories-2017.json 有 80 个 COCO 类别。本次按 evaluate.py 的六个别名映射逐项比对：motorbike、aeroplane、sofa、pottedplant、diningtable、tvmonitor；80 个名称均唯一匹配，没有未映射项。person 位于模型输出索引 0，映射到 COCO category_id=1。

这是文本映射的一致性检查，不证明未随附的 ONNX 模型实际使用相同输出通道顺序。所附标注只包含 person；若用它评估，COCOeval 只会有 person 类真值范围，不能形成完整 80 类成绩。示例默认使用 instances_val2017.json，而随附文件名为 instances_val2017_person.json，源码未显式绑定这个 person-only 文件（data_reader.py:L56-L73、e2e_user_yolov3_example.py:L50-L62、L121-L148）。

## 预处理与评价协议设计

主函数的默认标志 is_onnx_model_zoo_yolov3=False，选择 yolov3-608.onnx 的 variant 分支。校准和评价均实例化 YoloV3VariantDataReader，宽高显式设为 608，batch_size=1（e2e_user_yolov3_example.py:L81-L97、L121-L142）。该 reader 默认采用 yolov3_variant_preprocess_func：OpenCV 读取 BGR，直接缩放到 608×608（不保纵横比），转 RGB、转 CHW、float32 并除以 255（preprocessing.py:L127-L184）。精确 ONNX 输入 dtype/shape 未由模型文件核验。源码中还含有 416 PIL letterbox、128 填充及另一种 letterbox=114 预处理路径；它们不是该默认分支的 reader 默认值，不能混为同一输入合同。

variant 评价路径把候选置信度阈值设为 0.01（evaluate.py:L234-L247）；YOLO wrapper 配置按类别做 NMS、IoU 阈值 0.5（postprocessing.py:L94-L134、L248-L289）。之后调用 COCO bbox COCOeval 的 evaluate、accumulate、summarize（evaluate.py:L160-L178）。这是指标计算设计，不是已经生成的指标。代码未显式设置最大检测数或固定工作点匹配规则；依赖 COCOeval 默认参数和外部依赖版本。

## 精度证据与限制

主函数同时设置 ORT_TENSORRT_FP16_ENABLE=1 和 ORT_TENSORRT_INT8_ENABLE=1，并用 TensorRT Execution Provider 调用同一 yolov3-608.onnx 路径（e2e_user_yolov3_example.py:L173-L189）。校准函数创建熵校准表，但例程没有单独的 FP32 基线评价或纯 INT8 结果身份，也没有原始预测、AP/AR 输出或基线差值。因此当前材料不支持任何精度数值或量化损失（百分点）结论。P/R/F1、TP/FP/FN 和正常图误报率也没有实测材料。训练、C/RTL 及实板指标对这个外部 TensorRT 配方不适用或未提供。

静态实现提示：YoloV3DataReader 保存 self.preprocess_func，但其 base load_serial/load_batches 使用未限定的 preprocess_func 名称；所给模块没有该全局绑定（data_reader.py:L45-L73、L97-L100、L124-L135）。Variant 的 serial 路径使用 self.preprocess_func；variant batch 路径又使用未限定名称（L190-L195、L217-L229）。主配方当前 batch_size=1 走 serial 路径；非默认 base reader 和 batch 路径存在静态失败风险。未执行代码，不能报告实际运行时异常。

## 下一项最小证据

1. 固化并哈希实际校准图像 ID、来源 split、抽样 seed、校准表和实际验证文件列表；给出 train/val ID 重叠检查。
2. 提供确切 ONNX 文件及 SHA-256、输入名/shape/dtype、模型输出通道顺序。
3. 明确是否评估全 COCO Val，或 person-only 子集；若是后者，提供对应验证图片、完整 person 标注以及包含正常图的负样本集合。
4. 在同一冻结模型和验证集上分别运行 FP32 与目标 INT8 配置，保留 raw predictions、依赖版本、COCOeval 指标和可重算报告。量化损失按百分点计算。
5. 若需要固定工作点结果，再记录置信阈值、NMS IoU、匹配 IoU/规则、最大检测数、类别过滤，以及全部 TP/FP/FN 和正常图误报率。

## 哈希与执行记录

report.json 保存任务、manifest 与 10 个清单输入文件的写前/写后哈希、manifest 声明哈希/字节数对照、80 类映射明细、标注计数、源码证据引用和实际加载技能文件路径及哈希。所有任务/来源/输入文件在报告写入后复核未变化。简要操作日志见 execution_log.md。
