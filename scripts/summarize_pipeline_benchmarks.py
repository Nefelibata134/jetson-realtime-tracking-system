#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable


KEY_VALUE_PATTERN = re.compile(r"^([a-zA-Z][a-zA-Z0-9_]*)=(.*)$")


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = KEY_VALUE_PATTERN.match(line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def nested(document: dict[str, Any], *keys: str) -> Any:
    value: Any = document
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def per_frame(total_ms: Any, frames: Any) -> float | None:
    if not isinstance(total_ms, (int, float)) or not isinstance(frames, int):
        return None
    return float(total_ms) / frames if frames > 0 else None


def build_row(runtime_path: Path, metrics_path: Path) -> dict[str, object]:
    runtime = parse_key_values(runtime_path.read_text(errors="replace"))
    metrics = json.loads(metrics_path.read_text())
    pipeline = metrics.get("pipeline", {})
    outputs = metrics.get("outputs", {})
    video = outputs.get("annotated_video", {})
    clips = outputs.get("event_clips", {})
    device = metrics.get("device", {})
    video_encoder = (
        video.get("encoder")
        or runtime.get("output_encoder")
        or runtime.get("benchmark_output_encoder")
        or "mp4v"
    )
    video_bitrate_kbps = video.get("bitrate_kbps")
    if video_bitrate_kbps is None:
        video_bitrate_kbps = runtime.get(
            "benchmark_output_bitrate_kbps", "0"
        )

    passed = (
        runtime.get("runtime_exit_code") == "0"
        and nested(metrics, "status", "target_reached") is True
        and nested(metrics, "status", "recovery_exhausted") is False
    )
    row: dict[str, object] = {
        "status": "PASS" if passed else "FAIL",
        "timestamp": runtime.get("benchmark_timestamp", ""),
        "profile": runtime.get("benchmark_profile", ""),
        "model": runtime.get("benchmark_model", ""),
        "resolution": runtime.get("benchmark_resolution", ""),
        "power_mode": runtime.get("power_mode", ""),
        "power_mode_id": runtime.get("power_mode_id", ""),
        "clocks_locked": runtime.get("clocks_locked", "") == "true",
        "engine_sha256": runtime.get("engine_sha256", ""),
        "measured_frames": pipeline.get("measured_frames"),
        "drop_rate_percent": pipeline.get("drop_rate_percent"),
        "fps": pipeline.get("effective_fps"),
        "total_events": pipeline.get("total_events"),
        "video_encoder": video_encoder,
        "video_bitrate_kbps": video_bitrate_kbps,
        "snapshots_written": nested(outputs, "snapshots", "written"),
        "event_clips_completed": clips.get("completed"),
        "video_frames_written": video.get("frames_written"),
        "video_frames_dropped": video.get("frames_dropped"),
        "event_clip_encode_ms_per_frame": per_frame(
            clips.get("encoding_total_ms"), clips.get("frames_encoded")
        ),
        "event_clip_flush_ms": clips.get("flush_ms"),
        "video_encode_ms_per_frame": per_frame(
            video.get("encoding_total_ms"), video.get("frames_written")
        ),
        "video_flush_ms": video.get("flush_ms"),
        "power_mean_w": nested(device, "input_power_w", "mean"),
        "power_max_w": nested(device, "input_power_w", "max"),
        "gpu_max_percent": nested(device, "gpu_utilization_percent", "max"),
        "gpu_max_c": nested(device, "gpu_temperature_c", "max"),
        "ram_max_mb": nested(device, "ram_used_mb", "max"),
        "runtime_log": runtime_path.name,
        "metrics_json": metrics_path.name,
    }
    for name in (
        "queue_wait",
        "detector_preprocess",
        "tensorrt_inference",
        "detector_postprocess",
        "detection",
        "tracking",
        "event_analysis",
        "event_io",
        "event_io_active",
        "video_enqueue",
        "end_to_end",
    ):
        row[f"{name}_p95_ms"] = nested(
            metrics, "latency_ms", name, "p95"
        )
        row[f"{name}_samples"] = nested(
            metrics, "latency_ms", name, "samples"
        )
    return row


def latest_matrix(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    latest: dict[tuple[str, str, str, str, str, str], dict[str, object]] = {}
    for row in rows:
        key = (
            str(row["profile"]),
            str(row["model"]),
            str(row["resolution"]),
            str(row["power_mode_id"]),
            str(row["video_encoder"]),
            str(row["video_bitrate_kbps"]),
        )
        if key not in latest or str(row["timestamp"]) > str(latest[key]["timestamp"]):
            latest[key] = row
    resolution_order = {"720p": 0, "1080p": 1}
    return sorted(
        latest.values(),
        key=lambda row: (
            str(row["model"]),
            resolution_order.get(str(row["resolution"]), 99),
            str(row["power_mode_id"]),
            str(row["video_encoder"]),
            str(row["video_bitrate_kbps"]),
        ),
    )


CSV_FIELDS = [
    "status", "timestamp", "profile", "model", "resolution",
    "power_mode", "power_mode_id", "clocks_locked", "engine_sha256",
    "measured_frames", "drop_rate_percent", "fps", "total_events",
    "video_encoder", "video_bitrate_kbps",
    "queue_wait_p95_ms", "detector_preprocess_p95_ms",
    "tensorrt_inference_p95_ms", "detector_postprocess_p95_ms",
    "detection_p95_ms", "tracking_p95_ms", "event_analysis_p95_ms",
    "event_io_p95_ms", "event_io_active_p95_ms", "event_io_active_samples",
    "video_enqueue_p95_ms", "end_to_end_p95_ms", "snapshots_written",
    "event_clips_completed", "event_clip_encode_ms_per_frame",
    "event_clip_flush_ms", "video_frames_written", "video_frames_dropped",
    "video_encode_ms_per_frame", "video_flush_ms", "power_mean_w",
    "power_max_w", "gpu_max_percent", "gpu_max_c", "ram_max_mb",
    "runtime_log", "metrics_json",
]


def number(value: object, digits: int = 2) -> str:
    return "n/a" if value is None else f"{float(value):.{digits}f}"


def markdown(rows: list[dict[str, object]]) -> str:
    lines = [
        "# Jetson Full Pipeline Performance Matrix",
        "",
        "All runs use locked clocks and the complete detection, tracking, event evidence, and annotated video pipeline.",
        "Capture resolution changes while the YOLOX model input remains 416x416.",
        "",
        "## Critical Path",
        "",
        "| Status | Capture | Power | FPS | Drop % | Queue P95 | Pre P95 | TRT P95 | Post P95 | Track P95 | Event P95 | Active I/O P95 | E2E P95 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {status} | {resolution} | {power_mode} ({power_mode_id}) | {fps} | {drop} | {queue} | {pre} | {trt} | {post} | {track} | {event} | {event_io} | {e2e} |".format(
                status=row["status"], resolution=row["resolution"],
                power_mode=row["power_mode"], power_mode_id=row["power_mode_id"],
                fps=number(row["fps"]), drop=number(row["drop_rate_percent"]),
                queue=number(row["queue_wait_p95_ms"]),
                pre=number(row["detector_preprocess_p95_ms"]),
                trt=number(row["tensorrt_inference_p95_ms"]),
                post=number(row["detector_postprocess_p95_ms"]),
                track=number(row["tracking_p95_ms"]),
                event=number(row["event_analysis_p95_ms"]),
                event_io=number(row["event_io_active_p95_ms"]),
                e2e=number(row["end_to_end_p95_ms"]),
            )
        )
    lines.extend([
        "",
        "Latencies are milliseconds. Active I/O includes only frames that emitted a new event; inspect its sample count in the CSV.",
        "",
        "## Background Output And Device",
        "",
        "| Capture | Power | Encoder | kbps | Events | Snapshots | Clips | Clip ms/frame | Video written/dropped | Video ms/frame | Flush ms | Mean W | GPU max % | GPU max C | RAM max MiB |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in rows:
        lines.append(
            "| {resolution} | {power_mode} ({power_mode_id}) | {encoder} | {bitrate} | {events} | {snapshots} | {clips} | {clip_ms} | {written}/{dropped} | {video_ms} | {flush} | {power} | {gpu} | {temp} | {ram} |".format(
                resolution=row["resolution"], power_mode=row["power_mode"],
                power_mode_id=row["power_mode_id"], events=row["total_events"],
                encoder=row["video_encoder"],
                bitrate=row["video_bitrate_kbps"],
                snapshots=row["snapshots_written"], clips=row["event_clips_completed"],
                clip_ms=number(row["event_clip_encode_ms_per_frame"]),
                written=row["video_frames_written"], dropped=row["video_frames_dropped"],
                video_ms=number(row["video_encode_ms_per_frame"]),
                flush=number(row["video_flush_ms"]), power=number(row["power_mean_w"]),
                gpu=number(row["gpu_max_percent"]), temp=number(row["gpu_max_c"]),
                ram=number(row["ram_max_mb"]),
            )
        )
    lines.extend([
        "",
        "Background encode time is worker execution time divided by frames actually written; it is workload, not main-thread latency.",
        "",
    ])
    return "\n".join(lines)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=CSV_FIELDS,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("reports/benchmarks/pipeline/raw"))
    parser.add_argument("--csv", type=Path, default=Path("docs/benchmarks/jetson_full_pipeline_matrix.csv"))
    parser.add_argument("--markdown", type=Path, default=Path("docs/benchmarks/jetson_full_pipeline_matrix.md"))
    parser.add_argument("--all-runs", action="store_true")
    args = parser.parse_args()

    rows = []
    for metrics_path in sorted(args.input_dir.glob("*.metrics.json")):
        runtime_path = metrics_path.with_name(
            metrics_path.name.removesuffix(".metrics.json") + ".runtime.txt"
        )
        if runtime_path.is_file():
            rows.append(build_row(runtime_path, metrics_path))
    if not args.all_runs:
        rows = latest_matrix(rows)
    if not rows:
        raise SystemExit(f"no complete benchmark pairs found in {args.input_dir}")

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    write_csv(args.csv, rows)
    args.markdown.write_text(markdown(rows))
    print(f"runs={len(rows)}")
    print(f"csv={args.csv}")
    print(f"markdown={args.markdown}")


if __name__ == "__main__":
    main()
