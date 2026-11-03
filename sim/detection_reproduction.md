# 冻结模型的检测复现

本包按已确认范围复现硬件、固件和检测；从 epoch200 冻结模型开始，不重新训练。`data/dataset/` 仅含原 test 中按固定规则优选的 300 张图片与标签。预处理固定为 RGB、640×640 等比例居中补边、114 填充；置信度 0.25、类别内 NMS IoU 0.45、最多 300 个框。300 张属于展示子集，不替代完整 800 张历史测试统计。

## 环境与输入检查

已验证环境为 Windows x64、Python 3.12.14、PyTorch 2.14.1+cpu、NumPy 2.5.4、OpenCV 5.0.0.93。可在包外创建虚拟环境，再安装：

```powershell
python -m venv ..\repro_env
..\repro_env\Scripts\python.exe -m pip install -r build/requirements_reference.txt --extra-index-url https://download.pytorch.org/whl/cpu
```

以下命令只核对冻结模型、导出图、INT8 权重/量化参数、校准身份元数据、300 组图/标签及参考预测的 SHA256，无需 PyTorch，也不访问板卡：

```powershell
python -B sim/reproduce_detection.py --check
```

## 在电脑上复现全部 300 张

```powershell
..\repro_env\Scripts\python.exe -B sim/reproduce_detection.py --output-dir ../repro_output/reference300
```

输出目录必须尚不存在且在工程包外。入口直接使用包内整数图实现和冻结参数，不使用原机器目录，不导出/量化新权重。每张图独立重跑完整整数参考推理，再与 `report/selected_sample_predictions.json` 的离线预测比较；按类别、框坐标及置信度匹配，不依赖同分框的排列顺序。默认最大绝对误差为 1e-5，坐标单位为归一化模型输入坐标。检测数量、类别或数值超限都会返回非零退出码。

新目录中的 `result.json` 记录输入身份、每张图预测、差异、总耗时及后端。全部 300 张通过才输出 `PASS_DETECTION_300`；`--limit 2` 等只会输出局部检查状态。电脑参考运行不计入 FPGA 性能或实板验收。

## 板端检测与对照

由操作者按照 `board/sd_network_fix_v1/usage.md` 启动与冻结模型匹配的板卡，设置电脑 192.168.10.1/24、板卡 192.168.10.2:5001。确认网线和串口后，可运行 GUI，或使用批量对照入口：

```powershell
python -B board/run_desktop.py --host 192.168.10.2 --port 5001
..\repro_env\Scripts\python.exe -B sim/reproduce_detection.py --backend board --host 192.168.10.2 --port 5001 --output-dir ../repro_output/board300
```

多网卡时可加 `--local-address 192.168.10.1`。GUI 历史记录默认写入包外 `../repro_output/desktop_history`，可用 `--history-dir` 指定其他包外目录。板端入口沿用正式协议，逐请求校验模型 SHA、类别 SHA、输入/输出语义及 `runtime=board`，拒绝电脑模拟服务。默认比较容差为 1e-3；如需更严格的比较可显式设置 `--atol`，该值写入结果。它只发推理请求，不下载位流、不复位、不写 SD、不自动重试失败请求。连接或推理异常会直接失败。

本轮新执行的 300 张检测对照为电脑整数参考；板卡冷启动、重建产物的实板回归和 300 张实板对照仍需真实板卡结果，见 `report/missing_items.md`。历史两图/JTAG检查和原性能版的吞吐不替代这些验收。
