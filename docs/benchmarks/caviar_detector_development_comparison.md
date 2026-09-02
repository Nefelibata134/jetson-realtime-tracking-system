# CAVIAR 检测器开发集对比

## 结论

在三段 CAVIAR 开发视频、同一冻结规则和同一检测/跟踪阈值下，YOLOX-Tiny 的聚合
Precision 与 F1 高于 Nano，实时性仍有充足余量，因此选择 Tiny 作为 systemd 服务的
默认模型候选。这个选择不代表外部事件精度门禁已经通过，也不覆盖 Nano 的正式留出
FAIL 结果。

两种模型各自完整处理 `2,037/2,037` 帧，采集丢帧和帧序缺口均为 `0`。

| 模型 | TP | FP | FN | Precision | Recall | F1 | 跟踪帧 | 轨迹观测 | 检测数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| YOLOX-Nano | 4 | 4 | 5 | 50.00% | 44.44% | 47.06% | 563 | 785 | 2,190 |
| YOLOX-Tiny | 4 | 2 | 5 | 66.67% | 44.44% | 53.33% | 664 | 837 | 1,695 |

Tiny 的检测总数减少 `22.60%`，但跟踪帧增加 `17.94%`，轨迹观测增加 `6.62%`，
轨迹观测/检测数从 `35.84%` 提高到 `49.38%`。这说明它输出的候选框总体更少，
但更容易形成可持续跟踪；它没有解决所有远景漏检。

## 逐段事件结果

| 模型 | 序列 | 事件 | TP/FP/FN | Precision | Recall | F1 | 未计分输出 | 证据完整率 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Nano | `Walk1` | 双向穿线 | 2/0/3 | 100.00% | 40.00% | 57.14% | 0 | 100.00% |
| Tiny | `Walk1` | 双向穿线 | 1/0/4 | 100.00% | 20.00% | 33.33% | 0 | 100.00% |
| Nano | `Browse1` | 3 秒停留 | 0/0/2 | 不适用 | 0.00% | 0.00% | 2 | 100.00% |
| Tiny | `Browse1` | 3 秒停留 | 1/0/1 | 100.00% | 50.00% | 66.67% | 2 | 100.00% |
| Nano | `EnterExitCrossingPaths1front` | ROI 入侵 | 2/4/0 | 33.33% | 100.00% | 50.00% | 0 | 83.33% |
| Tiny | `EnterExitCrossingPaths1front` | ROI 入侵 | 2/2/0 | 50.00% | 100.00% | 66.67% | 0 | 100.00% |

Tiny 改善了停留召回并将入口误报减半，但穿线 Recall 从 `40.00%` 降到 `20.00%`。
因此当前决策是“默认采用 Tiny，继续在开发集分析穿线漏检”，而不是宣称 Tiny 在每种
事件上都更强。

`Browse1` 的未计分输出是 ROI 进入事件，不属于该序列的 `dwell` 计分类型。Nano 入口
序列的 6 个事件中有 1 个片段因同时活跃片段上限被跳过，所以证据完整率为 `83.33%`；
Tiny 的 4 个入口事件均完成截图与片段。

## 实时性与功耗

| 模型 | 序列 | FPS | TRT P95 | E2E P95 | 平均功率 | GPU 最高温度 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Nano | `Walk1` | 25.19 | 3.37 ms | 5.48 ms | 6.99 W | 56.56 C |
| Nano | `Browse1` | 25.09 | 3.37 ms | 5.49 ms | 6.99 W | 56.59 C |
| Nano | `EnterExitCrossingPaths1front` | 25.29 | 3.38 ms | 5.80 ms | 7.02 W | 56.41 C |
| Tiny | `Walk1` | 25.16 | 4.09 ms | 6.14 ms | 7.23 W | 56.50 C |
| Tiny | `Browse1` | 25.08 | 4.12 ms | 6.23 ms | 7.24 W | 56.56 C |
| Tiny | `EnterExitCrossingPaths1front` | 25.29 | 4.10 ms | 6.40 ms | 7.25 W | 56.47 C |

Tiny 的加权平均功率为 `7.24 W`，Nano 为 `6.99 W`，增加约 `0.25 W`。Tiny 的
TRT P95 不超过 `4.12 ms`，E2E P95 不超过 `6.41 ms`，远低于 25 FPS 的 `40 ms`
帧预算。

## 被测配置

- 平台：Jetson Orin Nano 8GB，25W 模式并锁定时钟。
- 输入：CAVIAR 384x288、25 FPS，经固定 H.264 MP4 本机 RTSP 实时回放。
- 规则：`configs/caviar/rules.frozen.json`。
- 固定阈值：score `0.3`、NMS `0.45`、track `0.5`、new-track `0.6`、buffer `30`。
- 测试提交：`03650fc8bbc62e1ef765f85664e8c2bb68868ae4`。
- Nano engine SHA-256：`59ef6ba75427881aa9fd70967e0ea44b94646e126a9070c4c6f2a9c2d43371bf`。
- Tiny engine SHA-256：`7d1a77e78fdd1fa4f53780fa0e77f5e0c9a3b77fb65eb165264631ab6a37533b`。

完整逐段数据见
[`caviar_detector_development_comparison.csv`](caviar_detector_development_comparison.csv)。

## 评估边界

本页只使用 `Walk1`、`Browse1` 和 `EnterExitCrossingPaths1front` 三段开发视频，不是
新的独立留出评估。此前四段留出视频已经查看过 Nano 结果，不能在切换模型后重复运行并
称为独立测试。Tiny 的最终外部精度需要选择新公开视频、冻结规则并执行新的留出轮次。

本轮没有调整检测阈值、ByteTrack 参数、ROI、警戒线、停留时长、真值或匹配规则。
原始运行目录保存在 Jetson：

- `outputs/caviar/development/nano-03650fc/`
- `outputs/caviar/development/tiny-03650fc/`
