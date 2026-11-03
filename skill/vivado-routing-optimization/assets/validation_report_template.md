# Vivado 实现/布线对照报告

> 将来源证据和 SHA 写在报告中。未知信息写“未知”，未运行写“未运行”。本模板不代表已经构建或通过。

## 目标与结论

- 目标：
- 验收范围：综合 / placement / physopt / route / 完整平台 / 板级（圈选）
- 当前结论：未运行 / 进行中 / 用户停止 / 工具失败 / 阶段通过 / 最终通过
- 一句话结论：
- 证据目录或报告链接：

## 运行身份与配置

| 项目 | 基线 | 候选 |
| --- | --- | --- |
| run ID / status / 退出码 |  |  |
| Vivado 版本与 build |  |  |
| 器件 / 顶层 |  |  |
| 时钟及目标周期 |  |  |
| RTL/网表源清单 SHA256 |  |  |
| XDC SHA256 |  |  |
| DCP 路径、阶段、SHA256 |  |  |
| build mode / strategy / directive |  |  |
| 线程数 / 主机与并发任务 |  |  |
| 受控变量及其它差异 |  |  |

## 时间与资源

| 项目 | 基线 | 候选 | 来源与口径 |
| --- | ---: | ---: | --- |
| 完整运行开始/结束时间 |  |  |  |
| 完整运行 elapsed wall time |  |  |  |
| synth / place / physopt / route elapsed |  |  |  |
| CPU time（单列，不与 elapsed 混用） |  |  |  |
| 峰值内存 / 主机总内存 |  |  |  |
| LUT / FF / BRAM / DSP |  |  |  |

## 最终质量门槛

| 指标 | 基线 | 候选 | 项目门槛 / 结论 |
| --- | ---: | ---: | --- |
| route 完成状态 / routable nets |  |  |  |
| fully routed / unrouted / partial / route errors |  |  |  |
| 节点重叠（仅诊断） |  |  |  |
| setup WNS / TNS / failing endpoints |  |  |  |
| hold WHS / THS / failing endpoints |  |  |  |
| pulse width WPWS / TPWS / failing endpoints |  |  |  |
| 时序覆盖 / 未约束端点 |  |  |  |
| DRC Error / Critical Warning |  |  |  |
| DRC Warning 数量 / 未解决项 |  |  |  |
| 功能仿真 / 数值一致性 |  |  | 未运行则保持未运行 |
| 板级功能 / 性能 |  |  | 未运行则保持未运行 |

## 差异解释与决策

- 实测事实：
- 推导值及公式：
- 未知 / 未收集：
- 是否达到预先约定的验收门槛：
- 失败、用户停止或未完成原因：
- 下一项最小实验、单一变量和停止条件：

## 附件索引

| 证据 | 相对路径 | SHA256 或其它身份 |
| --- | --- | --- |
| 运行 manifest |  |  |
| 日志 / 阶段报告 |  |  |
| route / timing / DRC 报告 |  |  |
| 资源 / 拥塞报告 |  |  |
