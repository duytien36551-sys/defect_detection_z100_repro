# 当前部署模型元数据

截至2026-11-03，当前部署候选为epoch200、PIN九类、640输入；类别、包格式与量化说明保存在本目录。相同字节的INT8权重副本已合并，请读取`../quantization/weights_int8.npz`；V8P为`../pin_epoch200_int8.v8p`，原始PT为`../pin_epoch200.pt`。相对路径以本文件所在目录为起点。此身份说明不表示本次重新训练或重新量化。

`export_snapshot/`为历史导出快照。其中与当前浮点导出相同的`model/weights_float.npz`已移出，保留位置为`../float_export/weights_float.npz`。该历史快照的量化权重字节与当前权重不同，因此没有作为重复文件删除，也不用于当前检测入口。
