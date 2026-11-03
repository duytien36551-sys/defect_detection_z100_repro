# 独立身份复核：01_identity_normal

**结论：** 提供的板端批次记录报告了一个运行身份，其模型 SHA-256 与较晚生成的候选构建清单中的模型包 SHA-256 相同。协议、类别摘要、输入/框坐标约定也由该运行记录报告。记录没有报告运行中的 ELF、bitstream 或 XSA 身份，因此不能确认该次运行使用了清单中的整套软件与硬件构建物。

## 范围与方法

仅读取本任务给出的 task、board_batch_acceptance.json、build_manifest.json、build_report.json，以及 zynq-model-identity 1.0.0-rc1 的 skill.md 和 references/workflow.md。未连接板卡或网络，未启动硬件，未重建产物。未读取其他案例、先前报告、索引或复核材料。

## 身份对照

| 字段 | 构建候选 | 板端批次记录 | 结论 |
|---|---|---|---|
| 目标配置 | 未提供独立的目标配置 | 记录称 runtime=board | 目标配置仍未定义 |
| 模型/包 | 清单模型与 sd_root/MODEL.V8P 记录为 SHA-256 f5394b31cf55502d6b3bc458b212db2c3422f8fe30dbdb509742f5c085a8d9b3 | identity_probe.model_sha256 及 model.sha256 同为 f5394b31cf55502d6b3bc458b212db2c3422f8fe30dbdb509742f5c085a8d9b3 | 记录值相同；未提供实际包文件供本次重算 |
| 模型结构 | 没有结构化的模型图/架构字段 | 未报告 | 未确认 |
| 类别 | 未提供类别文件或有序类别清单 | classes_sha256 为 5f6b28fea47fae5e78e5ab783049d5eb2c5b3a03ac255b94eb10ec95866807b1 | 只确认记录中的类别摘要值；类别名称、编号和顺序未知 |
| 输入/框约定 | 构建报告未声明运行输入合同 | 报告 rgb-u8-416-letterbox114，box_space=normalized-model-xyxy | 仅由板端记录支持，未与候选固件配置绑定 |
| 协议 | 构建报告未声明协议版本 | joint18-v8/1 | 仅由板端记录支持 |
| 固件/PL | 候选 ELF、BOOT.BIN、bitstream、XSA 有构建期摘要 | 运行探针没有 ELF、bitstream 或 XSA 摘要 | 不能确认这些候选构建物就是该次运行的构建物 |

板端记录的原始开始时间为 2026-10-15T19:15:59.749551+00:00；构建清单生成时间为 2026-10-18T13:16:26.190455+08:00。后生成的清单与较早运行记录具有相同的模型摘要，支持“模型摘要相同”的结论，但不能证明较早运行时已经使用后来记录的 ELF、PL 或 BOOT.BIN。

## 候选构建与硬件接口

清单记录 route_design Complete、setup slack 0.071 ns、hold slack 0.023 ns、ARM link PASS、ARM/XSA interface PASS、Bootgen readback PASS（3 partitions）。这些是清单声明的构建检查结果。

清单记录的主要产物如下。这里的摘要均为构建文件中的记录值，不是本次从二进制重算的值。

| 产物 | 记录 SHA-256 | 记录大小 |
|---|---|---:|
| sd_root/MODEL.V8P | f5394b31cf55502d6b3bc458b212db2c3422f8fe30dbdb509742f5c085a8d9b3 | 3,212,408 B |
| sd_root/BOOT.BIN | 31c806718163b938968661e6c9d703befbce32c095c7529c2044cccd2528890d | 4,379,208 B |
| programming/v8_tile64_board.elf | 198d962566ff42302f60e6f491aca9f155f508e4b62a752f095233d29d7a88e4 | 1,209,040 B |
| programming/tile64.bit | 03f73ed59fc7f8bc398995cbf4dc0cdf74d1fcf86f914073c188c365ef523f23 | 4,045,674 B |
| programming/tile64.xsa | 66669f87ef9a4ff2c3aa6fecc09adaee78beb0b0c6fa11a96b9e3ecf4db52f50 | 339,755 B |
| programming/fsbl.elf | 2a1223d0a7fd50b5cb31cb48ce90ebb9688a3def7893051fcd1410fe1a2d1037 | 669,272 B |

构建报告记录 ABI tile64-v1、64 lanes、max_taps=4091、max_sites=64，控制基址 0x43c10000 与继承 BSP 基址相同，DMA 实例 axi_dma_0，XSA DMA 长度宽度 20 bit。报告还记录 BSP 宽度 16 bit、有效宽度 20 bit 且来源为 XSA。报告明确标注 build_mode 为 “XSA metadata checked; physical board not verified”、physical_board_dma_width_verified=false，并要求匹配 routed tile64 bitstream。故这些内容只能支持候选构建的接口元数据，不能确认实板上的接口或 bitstream。

## 批次记录

记录标为 status=complete、dry_run=false、case_parity_pass=true、batch_acceptance_pass=true，20 条请求（PCB 10 条、pin 10 条），最低批次往返数为 20；记录内全部请求状态及结果比较均为 pass。该文件自述 cold boot 与 DMA recovery 是单独验收阶段；本记录不代表这两项已完成。

记录中的模型路径为 stage28_tile64_candidate\sd_root\MODEL.V8P，而构建报告的包路径为 stage28_p9995_integrated\MODEL.V8P。两个位置的记录摘要相同，因此目前是路径/来源标注不同、摘要声明一致；由于二进制未提供，无法进一步核验文件来源。

## 下一项最小证据

1. 从目标板同一次运行取得带板卡唯一 ID 的只读身份探针，记录协议、模型和类别摘要、输入/框合同及固件身份。
2. 通过运行端报告的摘要，或同一目标板、同一时间的编程/读回记录，把执行 ELF 与已加载 PL bitstream/XSA 绑定到这次运行，并与清单对比。
3. 提供类别顺序文件和预处理定义，并核对其 SHA-256。
4. 若要声称完整板端验收，再提供清单所述独立 cold-boot 与 DMA-recovery 阶段的结果。

## 来源与哈希

以下 SHA-256 是本次从任务和输入文件重算的值；完整清单产物及源码哈希声明保存在 report.json。原始输入在报告写入后复核，哈希未变化。

| 来源 | 本次计算 SHA-256 |
|---|---|
| task.md | bc43b30bda2e4804d45ee69085b01c2f38eb58402b1768813948ebd8ff0c52f4 |
| inputs/board_batch_acceptance.json | d1b566a36adaff79bd12fe09f8bff343214f2ecf2d9434d58837aca741135452 |
| inputs/build_manifest.json | 3ead1956a3e49b2821583793094a9aa5f2503d0b9f2dc50beb027f8a1082b3d7 |
| inputs/build_report.json | 137d9f6e6c18c0eb8ed032b528c785aa1df0ef64096b54fd70c9e38ac8c949f9 |

实际加载的技能文件及其重算哈希也记录在 report.json。
