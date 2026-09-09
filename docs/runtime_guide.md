# 运行与评估手册

本页保留详细命令、运行契约和历史基准复现入口。[项目概览](../README.md)汇总当前结论。
当前使用示例默认 Tiny416；标明 Nano 或留出的章节属于对应历史实验，不是默认部署命令。
运行设备实验前须核对资产、输入占用、功率状态及恢复安排，不应覆盖已有结果。

[构建与运行](#构建与运行) · [组件](#组件) · [运行证据](#运行证据) ·
[历史性能证据](#历史性能证据) · [检测矩阵](#jetson-检测基准矩阵) ·
[完整链路基准](#完整流水线基准) · [MOT17](#mot17-跟踪评估) · [CAVIAR](#caviar-外部事件验证)

## 构建与运行

<details>
<summary>展开主机构建、文件 / CSI / RTSP 命令及运行契约</summary>

以下当前使用示例统一使用 Tiny416；参数保持既有运行配置。ROI 与警戒线是归一化示例，
部署前须按场景定义。服务配置示例没有启用警戒线，不能仅启动服务就声称已验证三类事件。

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)"
ctest --test-dir build --output-on-failure
./build/edge_vision_contract_check
./build/edge_vision_frame_queue_check
./build/edge_vision_preprocess_check
./build/edge_vision_postprocess_check
./build/edge_vision_byte_tracker_check
```

默认目标需要 C++17 编译器、OpenCV、Eigen 3 和 `nlohmann-json3-dev`。Jetson 上的
TensorRT 目标需要显式启用。

在 Jetson 上配置 GStreamer 采集目标：

```bash
cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DEDGE_VISION_ENABLE_GSTREAMER=ON
cmake --build build -j"$(nproc)"

./build/edge_vision_capture_stream \
  --file input.mp4 --frames 300 --queue-capacity 4

./build/edge_vision_capture_stream \
  --csi --sensor-id 0 \
  --sensor-mode 4 \
  --capture-width 1280 --capture-height 720 --capture-fps 60 \
  --width 1280 --height 720 --fps 30 \
  --frames 300 --queue-capacity 4 \
  --reconnect-attempts 3 --reconnect-delay-ms 1000

./build/edge_vision_capture_stream \
  --rtsp rtsp://192.168.1.20:8554/camera \
  --rtsp-transport tcp \
  --rtsp-latency-ms 200 --rtsp-timeout-ms 5000 \
  --width 1280 --height 720 --fps 30 \
  --frames 300 --queue-capacity 4 \
  --reconnect-attempts 3 --reconnect-delay-ms 1000
```

采集工作线程在专用生产者线程运行输入源。消费者落后时，有界队列丢弃最旧帧，使内存
保持有界，并优先把新画面交给实时分析。可以设置 `--consumer-delay-ms` 制造受控
过载，观察队列深度、丢帧、序号间隙和队列驻留时间。

可以从 H.264 MP4 回放文件建立确定性 RTSP 服务：

```bash
sudo apt-get install -y python3-gi gir1.2-gst-rtsp-server-1.0
python3 scripts/serve_rtsp_replay.py videos/replay.mp4 \
  --port 8554 --mount /replay
```

客户端 URI 为 `rtsp://HOST:8554/replay`，其中 `HOST` 是服务器局域网地址。停止并
重启该进程即可制造受控网络视频中断，不必更改检测器或跟踪器配置。

RTSP URI 以进程参数传入。共享主机上不要在 URI 中嵌入长期凭据，因为本地进程检查可能
暴露它们；应优先使用无凭据的本地转发，或限制主机访问权限。

CSI 采集速率与应用输出速率分别配置。上述 IMX219 命令选择原生模式 4，即
1280x720/60 FPS，再由 `videorate` 向应用交付 30 FPS。意外 EOS 会触发有界流水线
重开。RTSP 支持 TCP 或 UDP 上的 H.264；TCP 是可靠传输默认值，受控网络中 UDP 可
降低传输延迟。无帧超时还能发现“连接仍打开但没有可解码帧”的情况。只有真正收到一帧，
重试预算、成功恢复计数和流代次才会推进，因此重复空重连不会被报告成恢复，也不会无限
持续。所有尝试结束后若仍未达到请求帧数，进程会报告恢复统计并以非零状态退出。

配置 TensorRT 运行时并执行 engine 探测：

```bash
cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DEDGE_VISION_ENABLE_TENSORRT=ON
cmake --build build -j"$(nproc)"
./build/edge_vision_trt_probe models/yolox_tiny_fp16.plan
./build/edge_vision_detect_image \
  models/yolox_tiny_fp16.plan input.jpg output.jpg
```

同时启用两个后端，从回放文件或 IMX219 连续检测与跟踪：

```bash
cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DEDGE_VISION_ENABLE_GSTREAMER=ON \
  -DEDGE_VISION_ENABLE_TENSORRT=ON
cmake --build build -j"$(nproc)"

./build/edge_vision_realtime_detect \
  --engine models/yolox_tiny_fp16.plan \
  --file input.mp4 \
  --warmup-frames 30 \
  --frames 300 \
  --queue-capacity 2 \
  --score-threshold 0.3 \
  --track-threshold 0.5 \
  --new-track-threshold 0.6 \
  --track-buffer 30 \
  --output-video outputs/replay_tracking.mp4 \
  --output-queue-capacity 4

./build/edge_vision_realtime_detect \
  --engine models/yolox_tiny_fp16.plan \
  --csi --sensor-id 0 \
  --sensor-mode 4 \
  --capture-width 1280 --capture-height 720 --capture-fps 60 \
  --width 1280 --height 720 --fps 30 \
  --warmup-frames 30 \
  --frames 300 \
  --queue-capacity 2 \
  --score-threshold 0.3 \
  --track-threshold 0.5 \
  --new-track-threshold 0.6 \
  --track-buffer 30 \
  --event-roi 0.20 0.35 0.80 0.95 \
  --event-dwell-seconds 3 \
  --event-line 0.15 0.70 0.85 0.70 \
  --event-line-direction any \
  --event-class-id 0 \
  --event-jsonl outputs/events/events.jsonl \
  --event-snapshot-dir outputs/events/snapshots \
  --event-clip-dir outputs/events/clips \
  --event-clip-pre-seconds 2 \
  --event-clip-post-seconds 3 \
  --output-video outputs/imx219_tracking.mp4 \
  --output-queue-capacity 4 \
  --metrics-json outputs/metrics/imx219_runtime.json \
  --tegrastats-interval-ms 500 \
  --reconnect-attempts 3 --reconnect-delay-ms 1000

./build/edge_vision_realtime_detect \
  --engine models/yolox_tiny_fp16.plan \
  --rtsp rtsp://192.168.1.20:8554/camera \
  --rtsp-transport tcp \
  --rtsp-latency-ms 200 --rtsp-timeout-ms 5000 \
  --width 1280 --height 720 --fps 30 \
  --warmup-frames 30 \
  --frames 300 \
  --queue-capacity 2 \
  --score-threshold 0.3 \
  --track-threshold 0.5 \
  --new-track-threshold 0.6 \
  --track-buffer 30 \
  --reconnect-attempts 3 --reconnect-delay-ms 1000
```

运行时报告生产、处理和丢弃帧数，队列深度与序号间隙，检测、轨迹和事件计数，唯一轨迹
ID，以及队列等待、检测预处理、TensorRT 执行、检测后处理、跟踪、事件分析、事件输出、
视频入队和端到端 P50/P95 延迟与有效吞吐。检测分数阈值必须低于 ByteTrack 轨迹阈值，
这样低置信度检测仍可参与第二阶段关联。小队列在采集快于推理时限制旧帧延迟。帧序号缺失
会通过空更新让跟踪器老化；输入源成功重连会增加流代次并清空所有旧轨迹。预热帧执行完整
流水线，但不计入检测、跟踪、延迟、吞吐和稳态丢帧统计。

`--metrics-json` 把最终状态发布为版本化 JSON。流水线计数、丢帧率、队列高水位、恢复
状态、检测/跟踪/事件总数、输出工作量、有效 FPS 和阶段延迟，会与专用后台
`tegrastats` 进程采样的 Jetson 遥测合并。设备采样从不在推理线程运行；如果
`tegrastats` 不可用，流水线指标仍会写出，并将 `device.available` 设为 `false`。
完整字段和单位见[运行时指标 Schema](metrics/runtime_metrics_schema.md)，实测采样
开销见[运行时遥测基准](benchmarks/runtime_telemetry_overhead.md)。

无人值守时，`--continuous` 移除有限帧目标，只保留最近
`--metrics-window-frames` 个延迟样本。SIGINT 与 SIGTERM 请求有序停止：采集停止，
待处理事件片段和标注视频完成，遥测结束，最终指标原子发布。systemd 下运行时会发送
`READY=1`、帧进度 watchdog 心跳和 `STOPPING=1`。真实帧停止时不再发送心跳，
systemd 因此能恢复停滞的采集或推理，而不是把空闲事件循环当成健康。

支持的无头安装、持久化目录、保留策略、服务检查和日志轮转命令见
[服务运维指南](operations/headless_service.md)。长期健康标准及可重复的进程/输入源
故障注入见[稳定性与恢复验证指南](operations/stability_validation.md)，实测 1 小时
持续运行和故障注入结果见[Jetson 服务稳定性报告](operations/stability_report.md)。

安全规则默认关闭。`--event-roi` 以 `LEFT TOP RIGHT BOTTOM` 定义归一化矩形区域，并
启用确认式 ROI 入侵。`--event-dwell-seconds` 为同一区域增加基于时间戳的停留规则。
`--event-line` 定义有限归一化线段，`--event-line-direction` 可选 `any`、
`negative-to-positive` 或 `positive-to-negative`。`--event-class-id` 选择一个
COCO 类别，也接受 `-1` 以对所有跟踪类别应用规则。规则使用每条轨迹边界框的底边中心；
流代次变化和时间线重启会清空全部事件状态。

`--event-jsonl` 启用版本化追加事件日志。可选截图和片段目录会把已验证证据路径写入记录。
先提交截图，再追加事件记录。事件片段使用有界原始帧预缓冲；实时线程只收集共享帧引用，
完整片段在有界后台队列编码。片段关闭并验证后才发布日志。运行时报告日志写入、重复跳过、
证据数量、事件 I/O 延迟与片段缓冲峰值。完整契约和持久化语义见
[安全事件记录 Schema](events/event_schema.md)。

`--output-video` 为可选参数。启用后，运行时把预热后的测量帧发送到专用有界写入队列，
并叠加每条活跃轨迹的边界框、底边中心、类别 ID、置信度和持久 track ID。配置的 ROI 与
线段保持可见，已触发事件标签和锚点会短暂保留，便于复核。编码过慢时丢弃最旧待输出帧，
不会阻塞采集、检测或跟踪。入队延迟、写入丢帧、队列高水位和最终刷新时间与实时流水线
延迟分别报告。后台编码总耗时与最大执行时间也会报告；仅看入队时间不能代表编码器或存储
成本。

标注输出默认使用 GStreamer `x264enc`，配置 `ultrafast`、`zerolatency`、一秒
GOP、无 B 帧、单参考帧和关闭自适应量化。目标码率由
`--output-bitrate-kbps` 设置，默认 `10000`。Jetson Orin Nano 没有 NVENC，因此
该路径有意采用调优后的 CPU H.264。`--output-encoder mp4v` 保留 OpenCV 兼容后端用于
对比，但实测 1080p MP4V 吞吐低于 30 FPS。所选编码器和码率都会写入运行日志与指标 JSON。

同步和异步输出实测见[标注视频输出基准](benchmarks/annotated_video_output.md)。

</details>

## 组件

| 组件 | 职责 | 状态 |
| --- | --- | --- |
| 运行契约 | Frame、输入源、检测器和检测结果类型 | 已实现 |
| GStreamer 输入源 | 文件回放、IMX219 CSI 采集、H.264 RTSP 接入 | 已实现 |
| 采集流水线 | 专用生产者线程、有界队列、时间戳、丢弃最旧帧背压 | 已实现 |
| TensorRT 运行时 | Engine 加载、CUDA 缓冲区与执行 | 已实现 |
| YOLOX 检测器 | 预处理、TensorRT 执行、网格解码、置信度过滤与 NMS | 已实现 |
| YOLO26n / YOLO26s 候选检测器 | 独立 RGB letterbox、one-to-many 解码与按类别 NMS，共用检测器接口 | 候选接口已实现；不作为当前默认或完整部署验收依据 |
| 连续检测与跟踪 | 采集、最新帧队列、TensorRT 检测、ByteTrack、标注视频与延迟统计 | 已实现 |
| 基准脚本 | 预热隔离、功率遥测、模型/分辨率/功率对比 | 已实现 |
| ByteTrack | Kalman 预测、两阶段关联、类别身份与重置语义 | 已实现 |
| 事件分析器 | 确认式 ROI 入侵、有限定向穿线、时间戳停留与流重置 | 已实现 |
| 事件证据 | 版本化 JSONL、持久化去重、截图和有界事件前后片段 | 已实现 |
| 遥测 | 版本化流水线指标及后台 Jetson 利用率、温度、功率和内存采样 | 已实现 |
| 恢复 | 有界 CSI/RTSP 重连、无帧超时、流代次与显式失败状态 | 已实现 |
| 服务生命周期 | 连续模式、SIGTERM 停止、systemd readiness、进度 watchdog、有界延迟窗口 | 已实现 |
| 运维 | systemd 安装、本地持久化事件 spool、保留定时器与日志轮转 | 已实现 |
| 稳定性验证 | 服务持续运行、资源趋势、进程崩溃注入与 RTSP 中断恢复 | 已实现 |

## 运行证据

以下历史记录摘录说明事件与指标字段，不作为当前候选之间的性能对照：

```text
event=line_crossing rule=directional-crossing track_id=2 class_id=0 frame=131 pts_ms=4366.667
target_reached=true
invalid_frames=0
output_frames=240
output_frames_dropped=0
event_analysis_p95_ms=0.006
end_to_end_p95_ms=15.038
effective_fps=30.093
```

采集视频、截图、片段、JSONL 日志和原始指标写入 `outputs/` 或配置的服务 spool。
这些运行产物被 Git 忽略，因此不会意外发布摄像头内容或设备生成的模型 engine。

## 历史性能证据

<details>
<summary>YOLOX-Nano 完整流水线矩阵、持续运行与恢复记录（不代表 Tiny 的结果）</summary>

下列八组数据均使用 YOLOX-Nano，在 Jetson Orin Nano 8GB 锁频状态下测得，保留原始数值。

| 配置 | 审计编码器 | FPS | 采集丢帧 | TRT P95 | 端到端 P95 | 视频写入 | 平均输入功率 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 720p, 25W | MP4V | 30.03 | 0.00% | 3.53 ms | 9.99 ms | 600/600 | 8.69 W |
| 720p, 25W | x264 | 30.03 | 0.00% | 3.49 ms | 9.93 ms | 600/600 | 8.94 W |
| 720p, MAXN_SUPER | MP4V | 30.04 | 0.00% | 3.22 ms | 8.46 ms | 600/600 | 9.00 W |
| 720p, MAXN_SUPER | x264 | 30.04 | 0.00% | 3.25 ms | 8.62 ms | 600/600 | 9.36 W |
| 1080p, 25W | MP4V | 30.04 | 0.00% | 3.49 ms | 14.17 ms | 280/600 | 8.93 W |
| 1080p, 25W | x264 | 30.00 | 0.00% | 3.75 ms | 13.67 ms | 600/600 | 9.35 W |
| 1080p, MAXN_SUPER | MP4V | 29.99 | 0.00% | 3.24 ms | 12.13 ms | 379/600 | 9.46 W |
| 1080p, MAXN_SUPER | x264 | 29.12 | 0.00% | 6.31 ms | 14.45 ms | 600/600 | 9.92 W |

上述完整流水线矩阵和 60 分钟稳定性记录使用 YOLOX-Nano，是不可改写的历史基线。
服务默认模型后续依据 CAVIAR 开发集 A/B 切换为 YOLOX-Tiny；两种模型的结果必须按各自
报告解释，不能把 Nano 性能表直接标成 Tiny。

YOLOX-S 以官方 `640x640` 输入完成了单独的可行性验证：720p 完整流水线在 25W 与
MAXN_SUPER 下均为 `30.03 FPS`、测量丢帧为 `0`、x264 写入 `600/600`；E2E P95
分别为 `13.02 ms` 和 `11.65 ms`。但 S 在冻结 CAVIAR 开发规则上的 F1 为
`50.00%`，低于 Tiny 的 `53.33%`，所以 Tiny 仍是默认模型。

补充验证：

- 60 分钟 CSI 服务持续运行实现 100% 活跃覆盖，进程零重启、watchdog 零停滞、
  真实帧零停滞、30.00 FPS、采集丢帧率 0.00%。
- 受控 SIGKILL 和 RTSP 输入中断测试都恢复到真实帧处理，而不是把“进程已重启但没有
  帧输入”误判为恢复。
- 固定 YOLOX-Tiny MOT17 留出划分得到 HOTA 38.89、IDF1 46.75、MOTA 39.19。
  该结果衡量完整的检测器与跟踪器组合。

详细协议、样本数和限制见[完整流水线矩阵](benchmarks/jetson_full_pipeline_matrix.md)、
[MOT17 跟踪结果](benchmarks/mot17_tracking_results.md)和
[服务稳定性报告](operations/stability_report.md)。S 的独立结果见
[YOLOX-S Jetson 可行性验证](benchmarks/yolox_s_feasibility.md)。

1080p 25W x264 测试中没有检测结果，也没有触发事件；它能验证审计编码连续性，但不能
验证活跃事件 I/O。1080p MAXN_SUPER x264 测试触发了入侵和停留证据，同时保存全部
600 个审计帧。两组 720p x264 测试也都触发了事件证据并保存全部 600 帧。

</details>

## Jetson 检测基准矩阵

<details>
<summary>展开 Nano / Tiny416 历史检测基准复现方法</summary>

基准脚本在两种 Jetson 功率模式下，对比 YOLOX-Nano 与 YOLOX-Tiny 的 720p 和 1080p
CSI 采集。两个检测器始终使用固定 `1x3x416x416` TensorRT 输入；采集分辨率衡量上游
摄像头、转换、缩放和内存传输负载，不改变模型张量契约。

下载已校验的上游模型，然后在目标 Jetson 上构建两个 FP16 engine：

```bash
bash scripts/fetch_yolox_nano.sh
bash scripts/fetch_yolox_tiny.sh

bash scripts/build_tensorrt_engine.sh \
  models/yolox_nano.onnx models/yolox_nano_fp16.plan
bash scripts/build_tensorrt_engine.sh \
  models/yolox_tiny.onnx models/yolox_tiny_fp16.plan
```

构建运行时并查看设备可用功率模式：

```bash
cmake -S . -B build-jetson-benchmark \
  -DCMAKE_BUILD_TYPE=Release \
  -DEDGE_VISION_ENABLE_GSTREAMER=ON \
  -DEDGE_VISION_ENABLE_TENSORRT=ON
cmake --build build-jetson-benchmark -j"$(nproc)"
ctest --test-dir build-jetson-benchmark --output-on-failure

sudo nvpmodel -q --verbose
```

在当前功率模式下运行一个受控组。分别对 `nano`、`tiny`、`720p`、`1080p`，
以及每个待比较功率模式重复命令。脚本只记录当前模式，不会自行切换。

```bash
bash scripts/run_jetson_benchmark.sh \
  --model nano \
  --engine models/yolox_nano_fp16.plan \
  --resolution 720p \
  --warmup-frames 30 \
  --frames 600
```

原始运行日志和 `tegrastats` 日志保存在 Git 忽略的
`reports/benchmarks/raw/`。全部组完成后生成受版本控制的对比表：

```bash
python3 scripts/summarize_jetson_benchmarks.py
```

生成的 CSV 与 Markdown 报告稳态 FPS、推理和端到端 P95、丢帧率、平均及峰值功率、
温度、GPU 利用率和每瓦 FPS。

</details>

## 完整流水线基准

<details>
<summary>展开历史 Nano 完整链路基准方法（涉及停服和锁频）</summary>

以下保留历史实验命令，不是默认启动方式，也不会自动完成退出恢复。实际执行前应核对
设备功率模式、保存原时钟状态，安排停服窗口和异常恢复；结束后恢复原配置并核验真实帧增长。

完整流水线基准固定 YOLOX-Nano，同时测量检测、ByteTrack、安全规则、事件截图和片段、
标注视频及 Jetson 遥测。脚本拒绝在 `edge-vision.service` 活跃或 GPU 未锁频时运行，
避免摄像头占用和频率状态在测试之间悄然变化。

选择功率模式、锁频，并运行两个采集分辨率：

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

选择并锁定第二种功率模式后重复，再生成受版本控制的报告：

```bash
python3 scripts/summarize_pipeline_benchmarks.py
```

协议和指标解释见[完整流水线基准测试协议](benchmarks/full_pipeline_benchmark.md)。

</details>

## MOT17 跟踪评估

离线评估按顺序处理每个所选 MOT17 帧，导出标准 10 列 MOTChallenge 结果，并用固定的
官方 TrackEval 计算 HOTA、IDF1、MOTA 和身份切换。每段物理 MOT17 视频只使用 FRCNN
命名副本，因为本系统自己提供检测结果。固定划分只使用公开训练序列；每条命令在推理前
校验元数据、真值、图像数和帧编号。

下面保留历史冻结留出结果的复现命令。该留出集已经消费，不用于后续候选调参；重复执行
不能称为新的独立验证，输出也不得覆盖已有结果。

<details>
<summary>展开固定 MOT17 评估命令</summary>

```bash
bash scripts/fetch_mot17.sh
bash scripts/fetch_trackeval.sh

cmake -S . -B build-mot17 \
  -DCMAKE_BUILD_TYPE=Release \
  -DEDGE_VISION_ENABLE_TENSORRT=ON
cmake --build build-mot17 -j"$(nproc)"

bash scripts/run_mot17_inference.sh \
  --engine models/yolox_tiny_fp16.plan \
  --seqmap configs/mot17/holdout.txt \
  --output-root outputs/mot17/holdout/final_tiny/edge_vision/data \
  --report-root reports/mot17/holdout/final_tiny/inference \
  --score-threshold 0.10 \
  --nms-threshold 0.45 \
  --track-threshold 0.30 \
  --new-track-threshold 0.40 \
  --match-threshold 0.80 \
  --track-buffer 30

bash scripts/run_trackeval_mot17.sh \
  --python /usr/bin/python3 \
  --seqmap configs/mot17/holdout.txt \
  --tracker-root outputs/mot17/holdout/final_tiny \
  --tracker-name edge_vision \
  --output-root reports/mot17/holdout/final_tiny/trackeval
```

</details>

固定 YOLOX-Tiny FP16 配置在三序列留出划分上达到 **HOTA 38.89**、**IDF1 46.75**
和 **MOTA 39.19**。各序列检测路径 P95 为 13.98 至 14.07 ms，包含帧封装、预处理、
TensorRT 推理和后处理，并非纯 TensorRT 耗时；ByteTrack P95 低于 0.32 ms。

固定的校准/留出划分、帧策略、依赖版本和报告命令见
[MOT17 评估协议](benchmarks/mot17_evaluation_protocol.md)，检测器对比与最终留出
指标见[MOT17 跟踪结果](benchmarks/mot17_tracking_results.md)。

## CAVIAR 外部事件验证

项目另选七段 CAVIAR 固定机位公开视频，分别为穿线、停留和 ROI 入侵建立开发/留出片段。
停留验证同时包含一个零事件负样本和一个正样本留出片段。CAVIAR 已有的人工边界框用于
生成独立事件真值；人工观看只确定业务区域并确认预期事件，不需要重新逐帧画框。规则在
任何留出推理前冻结，留出运行还要求显式 `--allow-holdout`，防止查看结果后继续调参。

当前人工复核后的规则已保存为
[`configs/caviar/rules.frozen.json`](../configs/caviar/rules.frozen.json)：穿线采用双向有限线段，
停留采用右侧展台区域和 `3.0` 秒阈值，ROI 入侵采用开放商店入口区域。三段开发视频生成的
`5/2/2` 个预期事件已逐项人工确认。

Jetson 25W 锁定时钟下的正式留出轮次完成了 `4,310/4,310` 帧，输入丢帧和帧序缺口均为
`0`。零事件负样本通过，但三个正样本序列均未达到冻结门限；合计 TP/FP/FN 为
`2/1/5`，聚合 Precision 为 `66.67%`、Recall 为 `28.57%`、F1 为 `40.00%`。该历史
YOLOX-Nano 配置的主要限制是低分辨率远景人物无法稳定转化为连续轨迹，不是 TensorRT
吞吐。

在相同三段开发视频、相同冻结规则与阈值下，Nano、Tiny 与 S 的聚合 F1 分别为
`47.06%`、`53.33%` 和 `50.00%`。S 使用官方 `640x640` 输入并消除了入口误报，
但没有检出停留事件；更多检测框没有转化为更高的整体事件 F1。因此 Tiny 仍是服务默认
模型，这不代表事件精度已经合格。完整开发集对比见
[CAVIAR 检测器开发集对比](benchmarks/caviar_detector_development_comparison.md)。

```bash
python3 scripts/fetch_caviar.py
python3 scripts/prepare_caviar_media.py
```

数据选择、人工复核步骤、MPEG2 到 H.264 MP4 转换、RTSP 实时回放、事件匹配标准和
完整运行命令见
[CAVIAR 公开场景外部事件验证协议](benchmarks/caviar_external_validation_protocol.md)，
逐段指标与事件截图见
[CAVIAR 外部事件验证结果](benchmarks/caviar_external_validation_results.md)。
