# CAVIAR 检测器开发集对比

## 结论

在三段 CAVIAR 开发视频、同一冻结规则和同一检测/跟踪阈值下，YOLOX-Tiny 的聚合
F1 仍是三种候选中最高的 `53.33%`。YOLOX-S 使用其官方 `640x640` 输入后可以在
Jetson Orin Nano 上实时运行，并把入口 ROI 的误报降为 `0`，但聚合 F1 为 `50.00%`，
且没有检出停留事件。因此 systemd 服务继续默认使用 Tiny，不因模型更大而切换。

三种模型各自完整处理 `2,037/2,037` 帧，采集丢帧和帧序缺口均为 `0`。本页是开发集
诊断，不代表外部事件精度门禁已经通过，也不覆盖 Nano 的正式留出 FAIL 结果。

| 模型 | 输入 | TP | FP | FN | Precision | Recall | F1 | 跟踪帧 | 轨迹观测 | 检测数 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| YOLOX-Nano | 416x416 | 4 | 4 | 5 | 50.00% | 44.44% | 47.06% | 563 | 785 | 2,190 |
| YOLOX-Tiny | 416x416 | 4 | 2 | 5 | 66.67% | 44.44% | **53.33%** | 664 | 837 | 1,695 |
| YOLOX-S | 640x640 | 3 | 0 | 6 | **100.00%** | 33.33% | 50.00% | 847 | 993 | 2,433 |

S 相比 Tiny 多输出 `43.54%` 的检测框、增加 `27.56%` 的跟踪帧和 `18.64%` 的轨迹
观测，但这些新增候选没有转化为更高的聚合事件 F1。结果说明当前瓶颈不仅是单帧漏检，
还包括轨迹连续性和事件规则所需的时序稳定性；单纯放大模型不能自动解决该问题。

## 逐段事件结果

| 模型 | 序列 | 事件 | TP/FP/FN | Precision | Recall | F1 | 未计分输出 | 证据完整率 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Nano | `Walk1` | 双向穿线 | 2/0/3 | 100.00% | 40.00% | 57.14% | 0 | 100.00% |
| Tiny | `Walk1` | 双向穿线 | 1/0/4 | 100.00% | 20.00% | 33.33% | 0 | 100.00% |
| S | `Walk1` | 双向穿线 | 1/0/4 | 100.00% | 20.00% | 33.33% | 0 | 100.00% |
| Nano | `Browse1` | 3 秒停留 | 0/0/2 | 不适用 | 0.00% | 0.00% | 2 | 100.00% |
| Tiny | `Browse1` | 3 秒停留 | 1/0/1 | 100.00% | 50.00% | 66.67% | 2 | 100.00% |
| S | `Browse1` | 3 秒停留 | 0/0/2 | 不适用 | 0.00% | 0.00% | 3 | 100.00% |
| Nano | `EnterExitCrossingPaths1front` | ROI 入侵 | 2/4/0 | 33.33% | 100.00% | 50.00% | 0 | 83.33% |
| Tiny | `EnterExitCrossingPaths1front` | ROI 入侵 | 2/2/0 | 50.00% | 100.00% | 66.67% | 0 | 100.00% |
| S | `EnterExitCrossingPaths1front` | ROI 入侵 | 2/0/0 | 100.00% | 100.00% | 100.00% | 0 | 100.00% |

S 在入口序列上达到 `2/0/0`，说明它对画面中较大人物的候选质量更好；但其穿线结果与
Tiny 相同，停留结果反而由 `1/0/1` 变为 `0/0/2`。因此 S 的优势是局部的入口精度，
不是三类事件的整体提升。

`Browse1` 的未计分输出是 ROI 进入事件，不属于该序列的 `dwell` 计分类型。评估器在
没有预测时把原始 Precision 数值约定为 `1.0`，表中写为“不适用”，避免将零预测误读为
没有误报且性能良好。Nano 入口序列的 6 个事件中有 1 个片段因同时活跃片段上限被跳过，
所以证据完整率为 `83.33%`；Tiny 与 S 的事件证据均完整。

## 实时性与功耗

| 模型 | 序列 | FPS | TRT P95 | E2E P95 | 平均功率 | GPU 最高温度 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Nano | `Walk1` | 25.19 | 3.37 ms | 5.48 ms | 6.99 W | 56.56 C |
| Nano | `Browse1` | 25.09 | 3.37 ms | 5.49 ms | 6.99 W | 56.59 C |
| Nano | `EnterExitCrossingPaths1front` | 25.29 | 3.38 ms | 5.80 ms | 7.02 W | 56.41 C |
| Tiny | `Walk1` | 25.16 | 4.09 ms | 6.14 ms | 7.23 W | 56.50 C |
| Tiny | `Browse1` | 25.08 | 4.12 ms | 6.23 ms | 7.24 W | 56.56 C |
| Tiny | `EnterExitCrossingPaths1front` | 25.29 | 4.10 ms | 6.40 ms | 7.25 W | 56.47 C |
| S | `Walk1` | 25.18 | 8.35 ms | 11.58 ms | 8.50 W | 56.25 C |
| S | `Browse1` | 25.10 | 8.39 ms | 11.95 ms | 8.51 W | 56.66 C |
| S | `EnterExitCrossingPaths1front` | 25.27 | 8.37 ms | 11.67 ms | 8.50 W | 56.47 C |

S 的加权平均功率为 `8.50 W`，Tiny 为 `7.24 W`，增加约 `1.26 W`。S 的 TRT P95
不超过 `8.40 ms`，E2E P95 不超过 `11.95 ms`，仍低于 25 FPS 的 `40 ms` 帧预算。
三者温度接近，短视频中未发现热限制。

## 被测配置

- 平台：Jetson Orin Nano 8GB，25W 模式并锁定时钟。
- 输入：CAVIAR 384x288、25 FPS，经固定 H.264 MP4 本机 RTSP 实时回放。
- engine 输入：Nano/Tiny 为 `1x3x416x416`，S 为官方 `1x3x640x640`。
- 规则：`configs/caviar/rules.frozen.json`。
- 固定阈值：score `0.3`、NMS `0.45`、track `0.5`、new-track `0.6`、buffer `30`。
- Nano/Tiny 测试提交：`03650fc8bbc62e1ef765f85664e8c2bb68868ae4`。
- S 测试提交：`59bfe3ad5385f062f5a471ceec6d18c506586a11`。
- Nano engine SHA-256：`59ef6ba75427881aa9fd70967e0ea44b94646e126a9070c4c6f2a9c2d43371bf`。
- Tiny engine SHA-256：`7d1a77e78fdd1fa4f53780fa0e77f5e0c9a3b77fb65eb165264631ab6a37533b`。
- S engine SHA-256：`af44d672c144be675bc3bbb2cad9a556224b144ee0e031d55de717dddf008d99`。

完整逐段数据见
[`caviar_detector_development_comparison.csv`](caviar_detector_development_comparison.csv)。
S 的 720p 完整流水线吞吐见
[`YOLOX-S Jetson 可行性验证`](yolox_s_feasibility.md)。

## 评估边界

本页只使用 `Walk1`、`Browse1` 和 `EnterExitCrossingPaths1front` 三段开发视频，不是
新的独立留出评估。此前四段留出视频已经查看过 Nano 结果，不能在切换模型后重复运行并
称为独立测试。Tiny 或 S 的最终外部精度需要选择新公开视频、冻结规则并执行新的留出轮次。

本轮没有调整检测阈值、ByteTrack 参数、ROI、警戒线、停留时长、真值或匹配规则。S 使用
官方 640x640 输入，而 Nano/Tiny 使用 416x416，因此这是“可直接部署候选”的工程比较，
不是只改变模型容量的严格消融实验。

原始运行目录保存在 Jetson：

- `outputs/caviar/development/nano-03650fc/`
- `outputs/caviar/development/tiny-03650fc/`
- `outputs/caviar/development/s-0fda71d/`

S 的目录名在提交前创建，因而保留父提交短号 `0fda71d`；被测源码与随后提交的
`59bfe3ad5385f062f5a471ceec6d18c506586a11` 完全一致，CSV 使用后者作为可追溯版本。
