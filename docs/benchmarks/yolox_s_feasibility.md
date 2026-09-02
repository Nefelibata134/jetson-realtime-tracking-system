# YOLOX-S Jetson 可行性验证

## 决策

YOLOX-S 可以在 Jetson Orin Nano 8GB 上承接当前 720p、30 FPS 的完整流水线。在 25W
和 MAXN_SUPER 两种锁频模式下，600 个测量帧均全部处理，采集丢帧与帧序缺口为 `0`，
x264 标注视频均写入 `600/600` 帧。因此 S 在吞吐层面可部署，不需要依赖 MAXN_SUPER
才能维持 30 FPS。

不过，S 在冻结 CAVIAR 开发规则上的聚合 F1 为 `50.00%`，低于 Tiny 的 `53.33%`。
它消除了入口 ROI 误报，却没有改善穿线召回，也没有检出 3 秒停留事件。当前 systemd
服务继续默认使用 Tiny；S 保留为已验证候选，而不是直接替换默认模型。

## 完整流水线结果

测试包括 CSI 采集、640x640 预处理、TensorRT FP16 推理、后处理、ByteTrack、三类事件
规则、事件证据模块、x264 标注视频以及设备遥测。采集源上限约为 30 FPS。

| 功率模式 | 测量帧 | 测量丢帧 | 帧序缺口 | FPS | TRT P95 | E2E P95 | 视频写入 | 视频编码 ms/帧 | 平均功率 | GPU 峰值 | GPU 最高温度 | RAM 峰值 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25W | 600 | 0 | 0 | 30.03 | 8.48 ms | 13.02 ms | 600/600 | 1.49 | 10.36 W | 41% | 57.91 C | 3,589 MiB |
| MAXN_SUPER | 600 | 0 | 0 | 30.03 | 7.82 ms | 11.65 ms | 600/600 | 1.32 | 10.83 W | 45% | 57.03 C | 3,597 MiB |

MAXN_SUPER 没有提高 FPS，因为采集源已经限制在 30 FPS；它把 TRT P95 降低约
`7.78%`，把 E2E P95 降低约 `10.48%`，同时平均输入功率增加约 `4.50%`。因此 25W
适合作为默认运行模式，MAXN_SUPER 只在需要额外延迟余量时启用。

25W 与 MAXN_SUPER 的 E2E P95 分别只占 30 FPS 帧预算 `33.33 ms` 的约 `39.1%` 和
`35.0%`。这说明当前吞吐有明显余量，但短时测试不能代替长时间温升与稳定性验证。

## 测量边界

- 每轮先预热 `30` 帧，再统计 `600` 帧；25W 和 MAXN_SUPER 的预热阶段分别丢弃 `7`
  和 `6` 个冷启动帧。这些帧没有混入正式测量，报告同时保留该事实。
- 25W 画面没有目标；MAXN_SUPER 画面有 `121` 个检测，但没有形成轨迹或事件。两轮验证了
  主流水线与连续标注编码，不能单独证明活跃事件片段编码吞吐。
- 活跃事件和证据链由同一 S engine 的三段 CAVIAR 开发视频补充验证；三段均无输入丢帧，
  事件证据完整率均为 `100%`。
- 两种模式是同一摄像头的顺序短测，不是同时采集；功率和温度差异只用于工程决策，不作
  严格硬件能效基准。
- TensorRT engine 与 Jetson GPU、TensorRT 版本和构建 profile 耦合，不能从仓库下载后
  直接跨设备复用。

逐项原始数值见 [`yolox_s_720p_pipeline.csv`](yolox_s_720p_pipeline.csv)，事件精度见
[`CAVIAR 检测器开发集对比`](caviar_detector_development_comparison.md)。原始 JSON 和
运行日志保存在 Jetson 的 `reports/benchmarks/pipeline/raw/`，并随本次桌面验证包归档。

## 模型与环境

| 项目 | 值 |
| --- | --- |
| 设备 | Jetson Orin Nano 8GB |
| 系统 | JetPack 6.2.1 / TensorRT 10.3 |
| ONNX | 官方 YOLOX-S，`1x3x640x640 -> 1x8400x85` |
| ONNX SHA-256 | `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063` |
| FP16 engine SHA-256 | `af44d672c144be675bc3bbb2cad9a556224b144ee0e031d55de717dddf008d99` |
| 被测代码提交 | `59bfe3ad5385f062f5a471ceec6d18c506586a11` |
| 输出编码 | GStreamer x264，10,000 kbps |

## 复现

在目标 Jetson 上下载、校验并构建 engine：

```bash
bash scripts/fetch_yolox_s.sh
bash scripts/build_tensorrt_engine.sh \
  models/yolox_s.onnx models/yolox_s_fp16.plan
```

选择功率模式、锁定时钟并运行完整流水线：

```bash
sudo systemctl stop edge-vision.service
sudo nvpmodel -m 1  # 改为 2 可测 MAXN_SUPER
sudo jetson_clocks

bash scripts/run_pipeline_benchmark.sh \
  --model s \
  --engine models/yolox_s_fp16.plan \
  --resolution 720p \
  --warmup-frames 30 \
  --frames 600 \
  --output-encoder x264 \
  --binary ./build-pipeline-benchmark/edge_vision_realtime_detect
```
