# 第三方许可与授权范围

项目贡献者拥有并有权授权的原创源码及原创文档采用根目录 [MIT 许可证](license)，允许复制、修改、发布和再分发，并要求保留版权与许可声明。第三方来源内容已有的许可证和版权声明继续适用；根许可证不将其重新授权为 MIT。

| 内容 | 位置或来源 | 许可处理 |
| --- | --- | --- |
| AMD/Xilinx BSP、FSBL、驱动及相关源码 | build/bsp_snapshot、build/firmware_portable、src/ps 等 | 保留各源文件声明；上游许可汇编见 [AMD/Xilinx 许可](build/firmware_portable/licenses/amd-xilinx-embeddedsw-license.txt)。 |
| lwIP 网络栈 | BSP/固件相关源码 | 保留原版权和 BSD 风格条款，见 [lwIP COPYING](build/firmware_portable/licenses/lwip-copying.txt)。 |
| 五项 Zynq/训练审计技能 | skill 各技能目录 | 各自已有 MIT license 原样保留。 |
| Ultralytics YOLO 软件及相关模型使用 | 训练、评估、部分参考服务及 ultralytics 依赖 | 上游公开许可为 GNU AGPL v3，也提供独立商业授权。本仓库不假设已取得商业授权。全文副本见 [AGPL v3](third_party_licenses/ultralytics_agpl3.txt)。 |
| NumPy、OpenCV、Pillow、PyTorch 等依赖 | build/requirements_*.txt | 由复现者另行安装，遵守各发行版许可。 |
| Vivado/Vitis、工具链和厂商生成物 | 外部工具及 board 中参考硬件/固件 | 工具、IP 和第三方生成内容继续适用其相应许可；未把厂商工具链作为开源软件发布。 |

Ultralytics 上游：[许可证](https://github.com/ultralytics/ultralytics/blob/main/LICENSE)、[许可说明](https://www.ultralytics.com/license)。与 AGPL 内容构成受其约束的组合或派生作品时，应遵守相应 AGPL 义务；不能因原创文件采用 MIT，就声称完整组合可以仅按 MIT 再分发。模型检查点及其导出、量化文件也不因新增根许可证而自动改为 MIT。

## 数据、权重与来源记录

data 中的图片、标注、模型权重和第三方来源资料作为原工程复现材料保留。根 MIT 仅授予贡献者实际拥有的权利，不额外授予第三方数据、模型、商标或个人资料的权利。原数据来源和再分发授权尚未完成独立确认，状态保留在 [待验收项](report/missing_items.md) 和来源材料中。公开可下载不表示这些非原创材料获得新的 MIT 授权。

本文件不修改模型身份、历史质量结论或板端验收状态。
