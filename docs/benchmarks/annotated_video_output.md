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

`Capture drops` occur before inference and can hide short-lived targets or
events. `Output drops` occur after detection and tracking, so they affect the
saved video but not the analytics result. Both counters remain observable
because recording continuity may still be required by downstream systems.
