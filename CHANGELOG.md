# Changelog

All notable changes to this project are documented in this file.

## [1.0.0] - 2026-08-23

### Added

- File, IMX219 CSI, and H.264 RTSP ingestion through GStreamer.
- Bounded drop-oldest capture queue with no-frame detection and finite source
  recovery.
- YOLOX-Nano and YOLOX-Tiny preprocessing, TensorRT execution, decoding, and
  NMS.
- Class-aware ByteTrack with Kalman prediction, two-stage association, lost
  track aging, and stream reset semantics.
- ROI intrusion, finite directional crossing, and timestamp-based dwell
  events.
- Versioned JSONL event journal, atomic snapshots, and bounded pre/post-event
  clips.
- Asynchronous annotated-video output with explicit backpressure metrics.
- Versioned atomic runtime metrics and background Jetson telemetry.
- systemd readiness, real-frame watchdog, graceful shutdown, retention, and
  log rotation.
- Reproducible Jetson pipeline benchmarks, MOT17 evaluation, one-hour service
  soak, and process/source fault injection.

### Validated

- 720p and 1080p complete-pipeline runs under 25W and MAXN_SUPER locked-clock
  configurations.
- A fixed MOT17 public-training holdout using pinned TrackEval.
- A 60-minute CSI service soak plus controlled main-process and RTSP outages.

### Known Limitations

- TensorRT plan files are not portable across Jetson models or TensorRT/CUDA
  software stacks and are therefore generated on the target device.
- The supplied COCO-pretrained YOLOX models are not fine-tuned for a specific
  deployment scene.
- OpenCV MP4V software encoding cannot preserve every 1080p/30 annotated frame
  on the measured device; the bounded output queue protects the analytics
  path by dropping stale output frames.
- Event evidence is persisted locally. Remote upload, authentication, and
  fleet management are outside this release.

[1.0.0]: https://github.com/Nefelibata134/jetson-realtime-tracking-system/releases/tag/v1.0.0
