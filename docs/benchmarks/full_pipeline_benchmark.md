# 完整流水线基准测试协议

该协议在不同对比测试之间保持检测器输入尺寸和事件配置不变，用于测量完整的 Jetson
视频分析负载。

## 固定负载

- 检测器：YOLOX-Nano TensorRT FP16，固定输入 `1x3x416x416`。
- 跟踪器：ByteTrack，轨迹阈值 0.50，新轨迹阈值 0.60。
- 输入：IMX219 CSI，以 30 FPS 交付应用。
- 事件规则：全画面 ROI 入侵、2 秒停留、所有类别。
- 证据：JSONL 日志、JPEG 截图、事件前后各 1 秒的视频片段。
- 审计输出：使用 GStreamer `x264enc`、`ultrafast`、`zerolatency`
  和 10 Mbps 的有界异步标注 MP4 写入器。
- 遥测：内部 `tegrastats` 采样器，间隔 500 ms。
- 预热：30 帧，不计入稳态统计。
- 测量窗口：每次 600 帧。

采集分辨率在 1280x720 与 1920x1080 之间切换，但模型张量始终是 416x416。因此该对比
测量的是摄像头转换、检测预处理、证据复制、标注、编码、内存与设备负载，而不是改变
模型精度或 TensorRT 张量尺寸。

## 受控变量

两个分辨率都要在 Jetson 25W 与 MAXN_SUPER 模式下运行。每次更改 `nvpmodel` 后执行
`sudo jetson_clocks`。测试脚本会记录当前功率模式，并拒绝 GPU 未锁频的运行。必须停止
systemd 服务，因为两个进程不能同时占用同一个 CSI 摄像头。

保持摄像头场景和照明稳定。至少一个被跟踪目标需要在全画面 ROI 内停留足够时间，以触发
入侵和停留证据；否则该次运行无法刻画活跃事件 I/O 与片段编码负载。

## 指标解释

关键路径表报告队列驻留、检测预处理、TensorRT 执行、检测后处理、跟踪、事件分析、
活跃事件 I/O，以及从采集到提交的 P95 延迟。这些阶段都在实时消费者线程执行，决定了
旧帧延迟风险。

标注视频和事件片段编码器在后台线程运行。队列高水位、丢帧、完成帧数、总编码时间、
单任务最大耗时与刷新耗时用于描述容量和积压。队列提交延迟不能表述为编码器执行延迟。

功率、利用率、温度和内存采样会一直持续到后台写入器结束，因此最终刷新工作也计入设备
遥测。有效 FPS 与稳态丢帧率仍只使用实时处理测量窗口。

## 复现命令

```bash
cmake -S . -B build-pipeline-benchmark \
  -DCMAKE_BUILD_TYPE=Release \
  -DEDGE_VISION_ENABLE_GSTREAMER=ON \
  -DEDGE_VISION_ENABLE_TENSORRT=ON
cmake --build build-pipeline-benchmark -j"$(nproc)"

sudo systemctl stop edge-vision.service
sudo nvpmodel -m 1
sudo jetson_clocks

bash scripts/run_pipeline_benchmark.sh \
  --model nano \
  --engine models/yolox_nano_fp16.plan \
  --resolution 720p \
  --binary ./build-pipeline-benchmark/edge_vision_realtime_detect

bash scripts/run_pipeline_benchmark.sh \
  --model nano \
  --engine models/yolox_nano_fp16.plan \
  --resolution 1080p \
  --binary ./build-pipeline-benchmark/edge_vision_realtime_detect
```

脚本默认使用 `--output-encoder x264 --output-bitrate-kbps 10000`。只有在复现旧版
OpenCV 基线时才传入 `--output-encoder mp4v`。编码器与码率都是矩阵键的一部分，
两个后端会分别保留，不会互相覆盖。

在模式 2 下重复两次运行，然后生成矩阵：

```bash
python3 scripts/summarize_pipeline_benchmarks.py
```

原始运行日志和指标 JSON 保存在 Git 忽略的 `reports/benchmarks/pipeline/raw/` 目录。
只有四组运行全部通过且事件与输出计数完成校验后，才提交生成的 CSV 和 Markdown。
