# Full Pipeline Benchmark Protocol

This protocol measures the complete Jetson video analytics workload without
changing detector input shape or event configuration between comparison runs.

## Fixed Workload

- Detector: YOLOX-Nano TensorRT FP16 with fixed `1x3x416x416` input.
- Tracker: ByteTrack with track threshold 0.50 and new-track threshold 0.60.
- Input: IMX219 CSI delivered to the application at 30 FPS.
- Event rules: full-frame ROI intrusion and two-second dwell, all classes.
- Evidence: JSONL journal, JPEG snapshots, one-second pre/post-event clips.
- Audit output: bounded asynchronous annotated MP4 writer using GStreamer
  `x264enc`, `ultrafast`, `zerolatency`, and 10 Mbps.
- Telemetry: internal `tegrastats` sampler at 500 ms.
- Warmup: 30 frames excluded from steady-state statistics.
- Measured window: 600 frames per run.

Capture resolution changes between 1280x720 and 1920x1080. The model tensor
remains 416x416, so the comparison captures camera conversion, detector
preprocessing, evidence copying, annotation, encoding, memory, and device
load rather than changing model accuracy or TensorRT tensor size.

## Controlled Variables

Each resolution is run under the Jetson 25W and MAXN_SUPER modes. Run
`sudo jetson_clocks` after every `nvpmodel` change. The harness records the
active mode and rejects unlocked GPU clocks. The systemd service must be
stopped because two processes cannot own the same CSI camera.

Keep the camera scene and illumination stable. At least one tracked object
must remain inside the full-frame ROI long enough to produce intrusion and
dwell evidence; otherwise the run cannot characterize active event I/O or
clip encoding.

## Metric Interpretation

The critical-path table reports P95 queue residence, detector preprocessing,
TensorRT execution, detector postprocessing, tracking, event analysis,
active-event I/O, and capture-to-submission latency. These stages execute on
the real-time consumer thread and determine stale-frame risk.

Annotated video and event clip encoders run on background threads. Their
queue watermark, drops, completed frames, total encoding time, maximum task
time, and flush time describe capacity and backlog. Queue submission latency
must not be presented as codec execution latency.

Power, utilization, temperature, and memory sampling remains active until
background writers finish, so final flush work is included in device
telemetry. Effective FPS and steady-state drop rate still use only the
measured real-time processing window.

## Commands

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

The harness defaults to `--output-encoder x264 --output-bitrate-kbps 10000`.
Pass `--output-encoder mp4v` only to reproduce the legacy OpenCV baseline.
Encoder and bitrate are part of the matrix key, so the two backends remain
separate rather than overwriting one another.

Repeat both runs in mode 2, then generate the matrix:

```bash
python3 scripts/summarize_pipeline_benchmarks.py
```

Raw runtime logs and metrics JSON stay under the ignored
`reports/benchmarks/pipeline/raw/` directory. Generated CSV and Markdown are
tracked only after all four runs pass and the event/output counters are
validated.
