# Tiny416/Tiny640 v4 预检失败记录

## 结论：预检 FAIL，尚未执行模型对照

2026-09-05 的 [v4 固定四组协议](tiny_resolution_caviar_v4.md) 在停止服务之前，
读取温度传感器时遇到未处理的异常。没有发出停止服务命令，也没有启动推理窗口。
16 份新板端 MOT 输出一致性核验和 12 次 CAVIAR development 对照全部为 **NOT_RUN**。
这是执行包装器的预检失败，不是 Tiny416/Tiny640 的模型质量或性能测试结果。
原 calibration FAIL、参数搜索矩阵和既有连续性诊断保持不变。

## 已核验的执行边界

- 提交为 `3b48161e50b43831b1577764a02869de62b22420`，板端工作树干净。
- 复用固定 engine、二进制和源码快照；模型未重建，未更改默认值、systemd 或运行参数。
- 原始 calibration 数据、三段开发视频、XML、生成真值及程序哈希在预检通过；失败后的资产复核也通过。
- 主机与板端各 20 项模拟服务/真实子进程保护测试通过。这些测试没有覆盖本次真实 sysfs 读取异常，
  不能以自测通过代替实际预检或真实停服恢复验证。
- 预检期间保持 25W；没有切换功率、锁频、读取 holdout、追加参数搜索或自动重试。
- 30 分钟停服预算尚未开始；没有用剩余预算重开轮次。原始目录、执行包和 FAIL 保留。

## 错误与只读复现

执行器报告 `TypeError: can't concat NoneType to bytes`。随后只读诊断复现了相同错误：

| 传感器 | 文本读取结果 | 直接系统读取结果 |
| --- | --- | --- |
| cv0-thermal | TypeError | EAGAIN，errno=11 |
| cv1-thermal | TypeError | EAGAIN，errno=11 |
| cv2-thermal | TypeError | EAGAIN，errno=11 |

调用链为温度快照函数、`Path.read_text()`、Python 3.10.12 的文本解码器；底层暂不可读时返回的
`None` 进入文本解码，触发字节拼接异常。包装器只捕获了 `OSError`，没有覆盖这一异常形式。
该路径发生在服务停止命令之前，推理、跟踪及事件规则没有执行。

直接读取已确认 EAGAIN，但传感器驱动为什么暂不可用尚未进一步确定；不能据此宣称过热、硬件故障或模型异常。
建议后续仅修复可选温度通道的读取与错误记录：对 EAGAIN 明确记录不可用、保留 errno 和通道身份，
不能将缺失温度填为零；必需的服务状态、实际 engine、功率、时钟约束和帧完整性检查仍应失败即停。
修复应补充 EAGAIN/空读取/有效值及失败前后状态测试，并在重新执行前完成独立检查。
本记录没有实施该修复，也没有放宽冻结一致性或计分要求。

## 逐视频与聚合：没有新评分

四组分别为 Tiny416、未调参 Tiny640、`t35_n35_m80` 和 `t30_n45_m75`；
五个阈值与 buffer 继续以 [机器可读协议](../../configs/benchmarks/tiny_resolution_caviar_v4.json) 为准。

| 配置 | Walk1：穿线 | Browse1：停留 | EnterExitCrossingPaths1front：入口入侵 | 聚合 |
| --- | --- | --- | --- | --- |
| Tiny416 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| 未调参 Tiny640 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| t35_n35_m80 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| t30_n45_m75 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |

上述每格的 TP/FP/FN、Precision/Recall/F1 均不可用，不能填写为零。
FPS、TRT/E2E/预处理/后处理/ByteTrack/事件 I/O P95、丢帧、序列缺口和对照期间资源指标也未测量。
既有 [同 GT 连续性诊断](tiny_resolution_continuity_v4_results.md) 仍反映覆盖与时长的取舍，
没有因这次预检获得新的板端支持或被推翻。历史 CAVIAR Tiny 阈值与本轮 Tiny416 不同，
后续也不能将与历史结果的差异单独归因于输入尺寸。

## 服务与证据

失败前真实帧从 335436 增至 335556。失败后的只读检查确认仍为同一 PID 6496，
active/running、NRestarts=0，实际进程 engine 仍是 `yolox_tiny_fp16.plan`，功率为 25W。
由于从未停服，恢复操作为不适用；原始汇总中的恢复状态为 `NOT RUN`，不能写成恢复 PASS。
失败后新的真实帧日志需要相应读取权限，本次只读诊断未取得；完整 EMC 快照未在异常前成功持久化。

[证据 JSON](tiny_resolution_caviar_v4_preflight_failure_evidence.json) 记录冻结协议、执行包、
engine 和原始失败/诊断文件的 SHA-256，以及全部 12 个逐视频空结果与 4 个聚合空结果。
原始日志和数据不进入仓库。没有独立留出、事件改善、CSI 实时性或默认迁移验收结论。
