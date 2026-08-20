# Runtime Telemetry Overhead

This benchmark checks whether background Jetson telemetry collection changes
the latency or throughput of the CSI detection and tracking pipeline.

## Configuration

- Device: NVIDIA Jetson Orin Nano 8GB
- Input: IMX219 CSI, native 1280x720 at 60 FPS, delivered at 30 FPS
- Detector: YOLOX-Nano TensorRT FP16, fixed 416x416 model input
- Tracker: ByteTrack
- Queue capacity: 2 frames with drop-oldest backpressure
- Warmup: 30 frames
- Measured window: 300 frames
- Device source: `tegrastats`

## Results

| Sampling interval | Device samples | Inference P95 ms | End-to-end P95 ms | Effective FPS | Steady-state drop rate |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 500 ms | 22 | 12.830 | 13.342 | 30.037 | 0.00% |
| 1000 ms | 11 | 12.821 | 13.389 | 30.093 | 0.00% |

The 500 ms run observed 7.164 W mean input power, 7.315 W maximum input
power, 43% maximum GPU utilization, 52.187 C maximum GPU temperature, and
2166 MiB maximum RAM use. The 1000 ms run observed 7.230 W mean input power.

## Interpretation

Doubling the interval halved the number of device samples as expected. The
inference P95 difference was 0.009 ms, the end-to-end P95 difference was
0.047 ms, and both runs sustained the requested 30 FPS without steady-state
drops. These differences are below ordinary run-to-run variation, supporting
the design choice to execute `tegrastats` parsing on a background thread
instead of the capture or inference thread.

The 500 ms interval is the default because it provides faster visibility into
short power, utilization, or thermal changes while remaining negligible for
this workload. A 1000 ms interval is suitable when coarser device telemetry is
acceptable.
