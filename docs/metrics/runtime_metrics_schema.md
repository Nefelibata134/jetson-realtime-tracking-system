# Runtime Metrics Schema

`edge_vision_realtime_detect` writes a final metrics document when
`--metrics-json PATH` is supplied. The document is published atomically after
capture and inference stop, so readers never observe a partially written JSON
file.

## Collection Model

- Pipeline counters and latency samples are collected in process.
- Jetson device metrics are read from a dedicated background `tegrastats`
  process at `--tegrastats-interval-ms` intervals.
- Device sampling does not execute on the capture or inference thread.
- A missing or failed `tegrastats` process does not fail inference. The device
  section reports `available: false` and preserves the sampler error.
- `schema_version` changes when field meaning or structure becomes
  incompatible.
- Finite runs summarize all measured frames. Continuous runs retain only the
  latest `latency_window_capacity` samples, preventing unbounded memory use.

## Top-Level Fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer contract version; currently `1` |
| `source` | `file`, `csi`, or `rtsp` |
| `status` | Completion and source health state |
| `pipeline` | Frame, queue, recovery, detection, tracking, and event metrics |
| `latency_ms` | Per-stage latency summaries in milliseconds |
| `outputs` | Event journal, snapshot, clip, and annotated video workload |
| `device` | Jetson memory, utilization, temperature, and input power summaries |

The `status` object records whether the run was finite or continuous, whether
SIGINT/SIGTERM requested shutdown, and the received signal number. Continuous
runs encode `target_frames` as `0`; a clean signal-driven stop has
`target_reached: false` and `shutdown_requested: true`.

## Metric Types

Counters such as `produced_frames`, `dropped_frames`, `total_detections`, and
`restart_attempts` describe work accumulated during one process run. Gauges
such as queue high-water mark, utilization, temperature, and power describe
observed state. Latency and device measurements use window summaries with
`mean`, `p95`, and `max`; latency also includes `p50`.

`drop_rate_percent` is calculated as:

```text
100 * dropped_frames / (measured_frames + dropped_frames)
```

Warmup drops remain available as `warmup_dropped_frames` but are excluded from
the steady-state drop rate.

Every latency summary includes `samples`, `mean`, `p50`, `p95`, and `max`.
An empty conditional stage has `samples: 0`; its zero-valued percentiles must
not be interpreted as measured zero latency.

## Stage Boundaries

| Stage | Start | End |
| --- | --- | --- |
| `queue_wait` | Frame capture timestamp | Detector call begins |
| `detector_preprocess` | Detector call begins | Letterbox/NCHW tensor is ready |
| `tensorrt_inference` | Tensor is ready | TensorRT output is synchronized and copied |
| `detector_postprocess` | TensorRT output is ready | Decode, thresholding, NMS, and coordinate restore finish |
| `detection` / `inference` | Detector call begins | Detection vector is returned |
| `tracking` | Detection finishes | ByteTrack update finishes |
| `event_analysis` | Tracking finishes | Rule state machines finish |
| `event_io` | Event analysis finishes | Synchronous snapshot/journal work and clip submission finish |
| `event_io_active` | Same as `event_io` | Same boundary, sampled only on newly triggered event frames |
| `video_enqueue` | Annotated video submission begins | Bounded writer queue accepts the frame |
| `end_to_end` | Frame capture timestamp | All real-time-thread output submissions finish |

`inference` remains an alias for total `detection` latency for compatibility
with earlier reports. It does not mean TensorRT execution alone.

## Output Workload

The `outputs` object separates asynchronous worker load from real-time-thread
latency:

- `event_journal` reports committed and duplicate event records.
- `snapshots` reports atomically written and reused JPEG evidence.
- `event_clips` reports clip accounting, encoded frames, queue watermark,
  background encode time, and final flush time.
- `annotated_video` reports submitted, written, and dropped frames, queue
  watermark, background encode time, and final flush time.

Encoding total divided by written frames is a workload rate, not per-frame
request latency. `video_enqueue` measures only bounded queue submission.

## Device Units

| Field | Unit |
| --- | --- |
| `ram_used_mb`, `ram_total_mb` | MiB as reported by `tegrastats` |
| `cpu_utilization_percent` | Mean utilization across online CPU cores |
| `gpu_utilization_percent` | GR3D utilization percent |
| `cpu_temperature_c` | Degrees Celsius |
| `gpu_temperature_c` | Degrees Celsius |
| `junction_temperature_c` | Degrees Celsius |
| `input_power_w` | Watts, converted from `VDD_IN` milliwatts |

Each device summary includes its own `samples` count because individual
Jetson releases may omit a field while still emitting the rest of the line.
Unavailable values are encoded as JSON `null` rather than zero.

## Example

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

The example is abbreviated; emitted documents include every field defined by
schema version 1.
