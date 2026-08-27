# Annotated Video Output Benchmark

This benchmark measures whether annotated MP4 encoding interferes with the
real-time detection and tracking path. The asynchronous writer uses a bounded
queue and drops the oldest pending output frame when encoding falls behind.
Capture, detection, tracking, and event processing continue independently.

## Configuration

- Device: Jetson Orin Nano 8GB
- Camera: IMX219 CSI, 1280x720 capture
- Detector: YOLOX-Nano FP16 TensorRT, 416x416 model input
- Tracker: ByteTrack
- Target rate: 30 FPS
- Warmup: 30 frames
- Measurement: 300 frames
- Capture queue capacity: 2

## Results

| Output mode | Output queue | Pipeline FPS | Capture drops | Capture queue P95 ms | Main-thread video P95 ms | Submitted | Written | Output drops |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Synchronous | n/a | 21.59 | 115 | 65.47 | 56.14 | 300 | 300 | 0 |
| Asynchronous | 4 | 30.04 | 0 | 0.70 | 1.30 | 300 | 298 | 2 |
| Asynchronous | 1 | 30.03 | 0 | 0.70 | 1.20 | 300 | 282 | 18 |

The asynchronous writer with capacity 4 increased pipeline throughput by
39.1% and eliminated capture-side drops. Main-thread video work fell from a
56.14 ms P95 synchronous encode to a 1.30 ms P95 enqueue operation. The
writer dropped 2 of 300 output frames while preserving all 300 frames for
detection and tracking.

Reducing the output queue from 4 to 1 kept the analytics path at 30 FPS with
zero capture drops, but increased output drops from 2 to 18. This confirms
that output backpressure is isolated from analytics and exposes the expected
memory-versus-recording-continuity tradeoff. Capacity 4 is the default for
the measured 720p pipeline.

## 720p Encoder Comparison

The 600-frame full-pipeline regression was repeated at 1280x720 after adding
the x264 backend. MP4V already preserved the complete 720p stream, while x264
reduced background encoding work from 30.93 to 4.68 ms/frame in 25W mode and
from 23.05 to 3.95 ms/frame in MAXN_SUPER mode.

| Power mode | Encoder | Events | Pipeline FPS | E2E P95 ms | Written/submitted | Output drops | Encode ms/frame | Mean W |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25W | MP4V | 2 | 30.03 | 9.99 | 600/600 | 0 | 30.93 | 8.69 |
| 25W | x264 | 4 | 30.03 | 9.93 | 600/600 | 0 | 4.68 | 8.94 |
| MAXN_SUPER | MP4V | 2 | 30.04 | 8.46 | 600/600 | 0 | 23.05 | 9.00 |
| MAXN_SUPER | x264 | 5 | 30.04 | 8.62 | 600/600 | 0 | 3.95 | 9.36 |

Both x264 runs preserved all 600 output frames while processing live event
evidence. GStreamer inspection confirmed 1280x720 H.264 Constrained Baseline
at 30/1 FPS and exactly 20 seconds for both files. Event counts are reported
as workload evidence, not compared as a quality metric because the live camera
scene differed between runs.

## 1080p Encoder Comparison

The OpenCV MP4V compatibility backend did not sustain the 30 FPS audit stream
at 1920x1080. With locked clocks it wrote 280/600 frames in 25W mode and
379/600 frames in MAXN_SUPER mode while the analytics path remained at 30 FPS.
Those measurements motivated the GStreamer x264 backend. Orin Nano does not
provide NVENC; the replacement therefore uses the vendor-recommended CPU H.264
approach with `ultrafast`, `zerolatency`, a one-second GOP, no B-frames, one
reference frame, and disabled adaptive quantization.

| Power mode | Encoder | Events | Pipeline FPS | E2E P95 ms | Written/submitted | Output drops | Encode ms/frame | Mean W |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25W | MP4V | 2 | 30.04 | 14.17 | 280/600 | 320 | 72.30 | 8.93 |
| 25W | x264 | 0 | 30.00 | 13.67 | 600/600 | 0 | 6.66 | 9.35 |
| MAXN_SUPER | MP4V | 2 | 29.99 | 12.13 | 379/600 | 221 | 53.26 | 9.46 |
| MAXN_SUPER | x264 | 2 | 29.12 | 14.45 | 600/600 | 0 | 7.45 | 9.92 |

Both x264 runs met the acceptance criterion: 600/600 written frames at
1080p30 with zero audit-output drops. GStreamer inspection confirmed a
1920x1080 H.264 Constrained Baseline stream at 30/1 FPS and exactly 20 seconds
for each 600-frame file. The 25W result sustained 29.996 pipeline FPS. Its
camera scene produced no detections, so that row validates encoding continuity
but not active event I/O. The MAXN_SUPER run emitted intrusion and dwell events
and still preserved every audit frame.

Run the controlled comparison with:

```bash
bash scripts/run_pipeline_benchmark.sh \
  --model nano \
  --engine models/yolox_nano_fp16.plan \
  --resolution 720p \
  --output-encoder x264 \
  --output-bitrate-kbps 10000 \
  --binary ./build-pipeline-benchmark/edge_vision_realtime_detect
```

Repeat with `--resolution 1080p` and under each locked power mode to reproduce
the complete comparison.

`Capture drops` occur before inference and can hide short-lived targets or
events. `Output drops` occur after detection and tracking, so they affect the
saved video but not the analytics result. Both counters remain observable
because recording continuity may still be required by downstream systems.
