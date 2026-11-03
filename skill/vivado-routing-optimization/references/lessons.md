# 经验与限制

## 阶段结果不能混用

综合、布局、物理优化、global route、详细布线和最终导出对应不同结果。某一阶段通过只支持该阶段的结论。若用户要求停止，报告“由用户停止”以及最后已完成的阶段；不要将它改写为工具失败、最终通过或时序失败。

## 中间指标不能当验收值

WNS/TNS、hold 和拥塞指标会随实现阶段变化。中间时序摘要适合诊断，不代替最终时序报告。overlap 数可能减少、增加或归零，但它既不是所有 nets 的布通状态，也不是可用的进度百分比。最终要查 route status 与时序、覆盖、DRC 报告。

## 比较必须保留输入身份

线程、directive、约束、checkpoint 及 RTL 的改变可能共同影响结果。一次只改一个因素，并记录 source/XDC/checkpoint 哈希、工具版本、器件、时钟和 run 配置。更改目标时钟或排除路径后，前后结果已不再代表同一验收目标。

增加线程可能降低某阶段耗时，也可能受内存、CPU 争用或工具阶段限制。CPU 时间增加不代表墙钟变慢；线程数不能只依据耗时推断是否生效。分开记录 CPU 与 elapsed，并记录峰值内存及其他任务。

## DRC 与时序报告要写全

Critical Warning 和 Warning 是不同等级。即使 Error/Critical Warning 为 0，仍要列出 Warning 数量、分组或未解决项，遵循项目的既定门槛。时序通过也要求检查时钟/I/O 覆盖和未约束端点；只报告 WNS 不能证明约束完整。

## 本工程历史结果与适用范围

随包的[最终硬件历史摘要](../../../report/final_hardware/synthesis_implementation_summary.md)记录 Vivado 2026.1 post-route：238,792/238,792 nets 完成，route errors 为 0，WNS/TNS 为 0.005/0 ns，WHS/THS 为 0.045/0 ns，Error/Critical Warning DRC 为 0，另有 1,447 个 Warning DRC 分组。它对应报告所述的历史最终输出，不证明任何新的源码构建、重新运行时间、RTL 功能或板端 FPS。

另一次新源码重建的本机记录（run ID `run-20261102T212058.072363Z`）标为 `STOPPED_BY_USER_VALIDATION_NOT_REQUIRED`：placement checkpoint 已产生，route 阶段仍记录为运行中，用户要求停止以避免不需要的硬件验证。它没有最终 route/timing 验收结论，也不能记为工具失败或最终通过；该外部记录及原始日志未随技能包分发。

本次包装整理没有启动 Vivado 或验证此技能。根目录其它技能的测试记录不代表本技能的验证；本技能没有自动化脚本或独立测试案例。下方示例中的输入和输出数值全部为合成数据。
