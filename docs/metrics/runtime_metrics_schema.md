# 运行时指标 Schema

提供 `--metrics-json PATH` 时，`edge_vision_realtime_detect` 会写出最终指标文档。
采集与推理停止后才原子发布该文档，因此读取端不会看到只写了一部分的 JSON。

## 采集模型

- 流水线计数器和延迟样本在进程内采集。
- Jetson 设备指标由专用后台 `tegrastats` 进程按
  `--tegrastats-interval-ms` 间隔读取。
- 设备采样不在采集或推理线程执行。
- `tegrastats` 缺失或失败不会让推理失败。设备部分会报告 `available: false`
  并保留采样错误。
- 字段含义或结构发生不兼容变化时，`schema_version` 才会升级。
- 有限运行汇总全部测量帧；连续运行只保留最近
  `latency_window_capacity` 个样本，防止内存无限增长。

## 顶层字段

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 整数契约版本，当前为 `1` |
| `source` | `file`、`csi` 或 `rtsp` |
| `status` | 完成状态和输入源健康状态 |
| `pipeline` | 帧、队列、恢复、检测、跟踪和事件指标 |
| `latency_ms` | 各阶段延迟汇总，单位毫秒 |
| `outputs` | 事件日志、截图、片段和标注视频工作量 |
| `device` | Jetson 内存、利用率、温度和输入功率汇总 |

`status` 对象记录运行是有限还是连续、SIGINT/SIGTERM 是否请求停止，以及收到的信号
编号。连续运行把 `target_frames` 编码为 `0`；通过信号干净停止时，
`target_reached: false` 且 `shutdown_requested: true`。

## 指标类型

`produced_frames`、`dropped_frames`、`total_detections` 和
`restart_attempts` 等计数器描述单次进程运行累计的工作量。队列高水位、利用率、温度
和功率等 gauge 描述观测状态。延迟和设备测量使用包含 `mean`、`p95`、`max` 的
窗口汇总，延迟还包含 `p50`。

`drop_rate_percent` 的计算式为：

```text
100 * dropped_frames / (measured_frames + dropped_frames)
```

预热阶段丢帧仍记录在 `warmup_dropped_frames`，但不计入稳态丢帧率。

每个延迟汇总都包含 `samples`、`mean`、`p50`、`p95` 和 `max`。没有样本的
条件阶段会显示 `samples: 0`；其为零的分位数不能解释成实测零延迟。

## 阶段边界

| 阶段 | 起点 | 终点 |
| --- | --- | --- |
| `queue_wait` | 帧采集时间戳 | 开始调用检测器 |
| `detector_preprocess` | 开始调用检测器 | Letterbox/NCHW 张量准备完成 |
| `tensorrt_inference` | 张量准备完成 | TensorRT 输出同步并复制完成 |
| `detector_postprocess` | TensorRT 输出准备完成 | 解码、阈值、NMS 和坐标还原完成 |
| `detection` / `inference` | 开始调用检测器 | 返回检测结果向量 |
| `tracking` | 检测完成 | ByteTrack 更新完成 |
| `event_analysis` | 跟踪完成 | 规则状态机执行完成 |
| `event_io` | 事件分析完成 | 同步截图/日志和片段提交完成 |
| `event_io_active` | 与 `event_io` 相同 | 边界相同，只在新事件触发帧采样 |
| `video_enqueue` | 开始提交标注视频 | 有界写入队列接收该帧 |
| `end_to_end` | 帧采集时间戳 | 实时线程的所有输出提交完成 |

为兼容早期报告，`inference` 仍是总 `detection` 延迟的别名，并不只代表 TensorRT
执行时间。

## 输出工作量

`outputs` 对象把异步工作线程负载与实时线程延迟分开：

- `event_journal` 报告已提交和被去重的事件记录。
- `snapshots` 报告原子写入和复用的 JPEG 证据。
- `event_clips` 报告片段计数、编码帧数、队列高水位、后台编码时间和最终刷新时间。
- `annotated_video` 报告提交、写入和丢弃帧数、队列高水位、所选编码器、H.264
  配置码率、后台编码时间和最终刷新时间。MP4V 兼容后端的 `bitrate_kbps` 为 `0`，
  因为该 OpenCV 路径不暴露可配置码率。

总编码时间除以实际写入帧数得到的是工作量速率，不是单帧请求延迟。`video_enqueue`
只测量有界队列提交。

## 设备单位

| 字段 | 单位 |
| --- | --- |
| `ram_used_mb`、`ram_total_mb` | `tegrastats` 报告的 MiB |
| `cpu_utilization_percent` | 在线 CPU 核心的平均利用率 |
| `gpu_utilization_percent` | GR3D 利用率百分比 |
| `cpu_temperature_c` | 摄氏度 |
| `gpu_temperature_c` | 摄氏度 |
| `junction_temperature_c` | 摄氏度 |
| `input_power_w` | 瓦，由 `VDD_IN` 毫瓦换算 |

每项设备汇总都有自己的 `samples`，因为不同 Jetson 版本可能缺少某个字段，但仍输出
同一行的其余字段。不可用值编码为 JSON `null`，而不是零。

## 示例

```json
{
  "schema_version": 1,
  "source": "csi",
  "status": {
    "target_reached": true,
    "invalid_frames": 0,
    "source_exhausted": false,
    "recovery_exhausted": false,
    "continuous": false,
    "shutdown_requested": false,
    "shutdown_signal": 0
  },
  "pipeline": {
    "measured_frames": 300,
    "dropped_frames": 1,
    "drop_rate_percent": 0.332,
    "effective_fps": 29.9,
    "latency_window_capacity": 300,
    "latency_window_samples": 300
  },
  "latency_ms": {
    "inference": {
      "mean": 13.1,
      "p50": 13.1,
      "p95": 13.4,
      "max": 70.0
    }
  },
  "device": {
    "available": true,
    "samples": 20,
    "sampler_error": null,
    "input_power_w": {
      "samples": 20,
      "mean": 8.1,
      "p95": 9.0,
      "max": 9.2
    }
  }
}
```

该示例经过精简；实际生成的文档包含 Schema 版本 1 定义的全部字段。
