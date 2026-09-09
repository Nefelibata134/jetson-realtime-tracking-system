# 历史与候选模型评估索引

当前部署主线为 YOLOX-Tiny416。本文保留其他模型与分辨率的资产入口、开发对照和限制，
不表示它们已用于默认服务。各轮原始协议、FAIL及历史报告不改写；不同功率、阈值、输入和数据划分的数字不能直接混用。

## Tiny416 与 Tiny640：CSI 720p 短测

以下两组均为 **MAXN_SUPER + jetson_clocks**，60 FPS 采集、30 FPS 交付，
每组预热 300 帧、测量 3,600 帧，启用 x264、截图与事件片段。

| 模型 | 有效 FPS | TRT P95 | E2E P95 | 采集丢帧 / 序列缺口 / 视频丢帧 | 标注帧写入 | 事件 / 截图 / 片段 |
| --- | ---: | ---: | ---: | --- | --- | --- |
| Tiny416 | 30.007089 | 3.87 ms | 8.77 ms | 0 / 0 / 0 | 3600/3600 | 4 / 4 / 4 |
| Tiny640 | 30.006253 | 7.09 ms | 11.50 ms | 0 / 0 / 0 | 3600/3600 | 5 / 5 / 5 |

两者在该短测负载下达到约 30 FPS，**不代表 25W 默认服务性能、充足余量或长期稳定通过**。
人物动作不完全一致，Tiny416 未出现穿线，测试窗口 OC3 保护计数增加 1；
完整同负载 A/B 未通过。预热丢弃另计为 6/5 帧。
E2E 计时到同步事件 I/O 与视频入队，不含传感器曝光、后台编码落盘或停止 flush。
逐阶段延迟、功耗、温度及恢复证据见[带事件 CSI 复测](tiny_resolution_csi_event_retest.md)。

## 为什么默认仍是 Tiny416

| 同条件开发对照 | Nano | Tiny416 | 取舍 |
| --- | ---: | ---: | --- |
| MOT17 calibration HOTA / IDF1 / MOTA | 29.19 / 34.50 / 24.38 | 33.31 / 39.80 / 29.65 | 整体质量改善；IDSW 从 227 增至 232 |
| CAVIAR development TP / FP / FN | 4 / 4 / 5 | 4 / 2 / 5 | 误报减少；穿线少检出一次，停留多检出一次 |
| 同轮 CAVIAR development F1 | 47.06% | 53.33% | 仅 9 项参考事件，不是独立外部验收 |

Tiny416 固定 MOT17 留出成绩为 **HOTA 38.89、IDF1 46.75、MOTA 39.19**；
留出与 calibration 不合并。Tiny640 提高了 MOT17 召回，但未形成一致的事件质量收益，
因此不替换默认模型。依据见[MOT17 结果](mot17_tracking_results.md)、
[历史 CAVIAR 模型对照](caviar_detector_development_comparison.md)。

Nano 的八组性能矩阵、60 分钟稳定性和恢复记录保留为历史基线，不能改名为 Tiny 的结果：
[历史矩阵](jetson_full_pipeline_matrix.md) ·
[完整矩阵摘录与复现入口](../runtime_guide.md#历史性能证据) ·
[稳定性报告](../operations/stability_report.md)。
历史 Nano CAVIAR 外部留出F1为40.00%、结论FAIL，不是Tiny的留出结果，见
[外部事件验证报告](caviar_external_validation_results.md)。

## 模型资产与复现入口

仓库只跟踪获取/导出/构建工具、模型元数据和校验和，不分发权重、ONNX 或 TensorRT engine。
官方 Nano/Tiny416/S ONNX 获取入口：

```bash
bash scripts/fetch_yolox_nano.sh
bash scripts/fetch_yolox_tiny.sh
bash scripts/fetch_yolox_s.sh
```

来源、哈希和输入输出契约见 [Nano](../../models/yolox_nano.json)、
[Tiny416](../../models/yolox_tiny.json)、[S](../../models/yolox_s.json)。
Tiny640 的同权重导出与 416 等价检查见[资产契约](../models/yolox_tiny_640.md)。
YOLO26n/s 共用独立导出与 Detector 适配，保留为显式候选，分别见
[YOLO26n](../models/yolo26n.md)、[YOLO26s](../models/yolo26s.md)；
其输出不复用 YOLOX 网格解码。导出或最小推理成功均不等于部署验收。

### 开发证据

| 验证范围 | 核心结果与限制 | 证据 |
| --- | --- | --- |
| v1：25W，同阈值 MOT17 calibration | Tiny640 Recall 47.06% 对 Tiny416 34.14%，但 IDSW 352 对 232，小目标中断增加；原质量门槛 FAIL | [协议](tiny_resolution_protocol.md) · [结果](tiny_resolution_results.md) |
| v2：MAXN_SUPER 锁频 CSI 720p | 首轮数值实时性达标但无事件，完整链路门槛 FAIL；带事件复测仍不满足同负载 A/B | [首轮](tiny_resolution_development_v2_results.md) · [带事件复测](tiny_resolution_csi_event_retest.md) |
| v3：27 组有界 calibration 参数搜索 | 没有配置满足该轮全部无回退条件；完整矩阵保留覆盖、误报、IDSW 和中断取舍 | [参数矩阵与结论](tiny_resolution_tuning_v3_results.md) |
| v4：四组 CAVIAR development | Tiny416 / 未调参 Tiny640 / 两组调参 Tiny640 的 F1 为 58.82% / 42.11% / 38.10% / 42.11%；640 穿线漏报和 ROI 误报更多 | [同 GT 连续性](tiny_resolution_continuity_v4_results.md) · [事件结果](tiny_resolution_caviar_v4_results.md) |
| v5：VIRAT 同源原生 720p / 384×216 | 原生输入两模型 F1 均 66.67%，低清分别 66.67% / 70.59%；未证实原生清晰度带来更大 640 收益 | [源分辨率对照](tiny_source_resolution_v5_results.md) |
| v6：MEVA 近景，派生 720p | Tiny416 / Tiny640 为 13/8/1 与 13/9/1（TP/FP/FN），F1 74.29% / 72.22%；640 没有新增正确事件 | [协议](tiny_near_field_v6.md) · [逐类结果与诊断](tiny_near_field_v6_results.md) |


v4 阈值不同于历史 Nano/Tiny/S 对照，不能把跨轮差异单独归因于模型。
v5/v6 为顺序 PNG 开发回放，不是 CSI 实时性测试；v6 三段来自同机位同源视频，
1920×1072 补边缩至 1280×720，源 PTS 缺失，使用明确标记的派生时间，**不是原生 720p**。
全部开发结果均不能替代新的独立外部验证，原协议门槛与 FAIL 保留。
