#!/usr/bin/env python3
"""Fixed CSI development recipe and conservative evidence validation; no device mutation."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

FROZEN_RECIPE_SHA256 = "ff9e83b36bdef8959f32bc62fabc11abeb18d80f230dc19c86fb2b1ad6aad85b"


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if (config["protocol_id"] != "tiny-resolution-development-v2"
            or config["holdout_allowed"] is not False
            or config["default_switch_authorized"] is not False
            or config["tuning_authorized_by_this_config"] is not False):
        raise ValueError("Wrong development protocol or unsafe authorization")
    if config["thresholds"] != dict(score=.10, nms=.45, track=.30, new_track=.40, match=.80, buffer=30):
        raise ValueError("First comparison requires unchanged explicit thresholds")
    if (config["order"] != ["tiny416", "tiny640"] or config["power_mode_id"] != 2
            or config["power_mode"] != "MAXN_SUPER" or config["jetson_clocks"] is not True):
        raise ValueError("Wrong model order or power/clock contract")
    if (config["warmup_frames"] != 300 or config["measured_frames"] != 3600
            or config["fps_window_frames"] != 600 or config["model_timeout_seconds"] != 240):
        raise ValueError("Measurement window changed")
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if hashlib.sha256(canonical).hexdigest() != FROZEN_RECIPE_SHA256:
        raise ValueError("Frozen v2 geometry, inputs, outputs, assets or gates changed; use a new protocol version")
    return config


def command(config, binary, engine, run):
    run = Path(run)
    args = [str(binary), "--engine", str(engine), "--detector", "yolox", "--csi"]
    for key, value in config["csi"].items():
        args += ["--" + key.replace("_", "-"), str(value)]
    for flag, key in (("warmup-frames", "warmup_frames"), ("frames", "measured_frames"),
                      ("queue-capacity", "queue_capacity"), ("output-queue-capacity", "output_queue_capacity")):
        args += ["--" + flag, str(config[key])]
    for key, flag in (("score", "score-threshold"), ("nms", "nms-threshold"),
                      ("track", "track-threshold"), ("new_track", "new-track-threshold"),
                      ("match", "match-threshold"), ("buffer", "track-buffer")):
        args += ["--" + flag, str(config["thresholds"][key])]
    events, output = config["events"], config["outputs"]
    args += ["--event-roi", *map(str, events["roi"]), "--event-line", *map(str, events["line"])]
    for flag, value in (("event-line-direction", events["line_direction"]),
                        ("event-dwell-seconds", events["dwell_seconds"]),
                        ("event-class-id", events["class_id"]),
                        ("event-clip-pre-seconds", events["clip_pre_seconds"]),
                        ("event-clip-post-seconds", events["clip_post_seconds"]),
                        ("event-jsonl", run / "events.jsonl"),
                        ("event-snapshot-dir", run / "snapshots"),
                        ("event-clip-dir", run / "clips"),
                        ("output-video", run / "annotated.mp4"),
                        ("output-encoder", output["encoder"]),
                        ("output-bitrate-kbps", output["bitrate_kbps"]),
                        ("metrics-json", run / "metrics.json"),
                        ("tegrastats-interval-ms", config["telemetry_interval_ms"]),
                        ("log-interval", output["log_interval"]),
                        ("reconnect-attempts", 3), ("reconnect-delay-ms", 1000)):
        args += ["--" + flag, str(value)]
    return args


def frame_records(records):
    result = []
    for record in records:
        line = record["line"]
        if not line.startswith("frame=") or " e2e_ms=" not in line:
            continue
        fields = dict(token.split("=", 1) for token in line.split() if "=" in token)
        row = {key: float(value) for key, value in fields.items() if key.endswith("_ms")}
        if not all(math.isfinite(value) and value >= 0 for value in row.values()):
            raise ValueError("Invalid per-frame latency")
        row.update(frame=int(fields["frame"]), monotonic_ns=int(record["monotonic_ns"]))
        result.append(row)
    if any(b["frame"] <= a["frame"] or b["monotonic_ns"] <= a["monotonic_ns"]
           for a, b in zip(result, result[1:])):
        raise ValueError("Duplicate/out-of-order frame or observation clock")
    return result


def summarize(config, metrics, records, exit_code):
    frames = frame_records(records)
    size = config["fps_window_frames"]
    windows = []
    for start in range(0, len(frames), size):
        chunk = frames[start:start + size]
        seconds = (chunk[-1]["monotonic_ns"] - chunk[0]["monotonic_ns"]) / 1e9 if len(chunk) > 1 else 0
        windows.append({"window": start // size + 1, "frames": len(chunk),
                        "complete": len(chunk) == size, "elapsed_seconds": seconds,
                        "observer_fps": (len(chunk) - 1) / seconds if seconds else None})
    p, status, outputs = metrics["pipeline"], metrics["status"], metrics["outputs"]
    video, clips = outputs["annotated_video"], outputs["event_clips"]
    gate, n = config["gate"], config["measured_frames"]
    fps, e2e = p["effective_fps"], metrics["latency_ms"]["end_to_end"]["p95"]
    finite = lambda value: isinstance(value, (int, float)) and math.isfinite(value)
    checks = {
        "exit_code": exit_code == 0,
        "schema_source": metrics["schema_version"] == 1 and metrics["source"] == "csi",
        "target_reached": status["target_reached"] is True and status["continuous"] is False,
        "no_invalid_frames": status["invalid_frames"] == 0,
        "warmup": p["warmup_frames"] == config["warmup_frames"],
        "complete_frames": p["measured_frames"] == p["target_frames"] == len(frames) == n,
        "fps": finite(fps) and fps >= gate["effective_fps_min"],
        "e2e": finite(e2e) and e2e <= gate["e2e_p95_ms_max"],
        "capture_drops": p["dropped_frames"] == gate["capture_drops_max"],
        "drop_accounting": p["dropped_frames_total"] == p["dropped_frames"] + p["warmup_dropped_frames"],
        "sequence_gaps": p["sequence_gaps"] == gate["sequence_gaps_max"] and
                         all(b["frame"] == a["frame"] + 1 for a, b in zip(frames, frames[1:])),
        "no_restart": p["restart_attempts"] == p["restart_successes"] == p["tracker_resets"] == 0,
        "video": video["enabled"] and video["frames_written"] == video["frames_submitted"] == n and
                 video["frames_dropped"] == gate["video_drops_max"],
        "output_recipe": video["encoder"] == config["outputs"]["encoder"] and
                         video["bitrate_kbps"] == config["outputs"]["bitrate_kbps"] and
                         p["queue_capacity"] == config["queue_capacity"],
        "event_types": all(p[key + "_events"] >= 1 for key in gate["event_types_required"]),
        "event_files": outputs["event_journal"]["enabled"] and outputs["event_journal"]["records_written"] > 0 and
                       outputs["snapshots"]["enabled"] and outputs["snapshots"]["written"] > 0 and
                       clips["enabled"] and clips["started"] == clips["completed"] > 0 and clips["skipped"] == 0,
        "latency_samples": all(metrics["latency_ms"][key]["samples"] == n for key in
                               ("end_to_end", "tensorrt_inference", "detector_preprocess", "detector_postprocess", "tracking", "event_io")),
        "active_io_samples": metrics["latency_ms"]["event_io_active"]["samples"] > 0,
        "telemetry": metrics["device"]["available"] and all(
            metrics["device"][key]["samples"] > 0 and finite(metrics["device"][key]["max"])
            for key in ("ram_used_mb", "cpu_utilization_percent", "gpu_utilization_percent", "input_power_w", "junction_temperature_c")),
    }
    return {"protocol_id": config["protocol_id"], "numeric_gate": "PASS" if all(checks.values()) else "FAIL",
            "overall": "REVIEW_REQUIRED" if all(checks.values()) else "FAIL", "checks": checks,
            "scene_review": "PENDING", "video_decode_verification": "PENDING",
            "runtime_effective_fps": fps, "e2e_p95_ms": e2e,
            "warmup_dropped_frames": p["warmup_dropped_frames"], "measured_dropped_frames": p["dropped_frames"],
            "observer_windows": windows, "observer_window_scope": "diagnostic_stdout_receipt_not_runtime_clock",
            "quality_acceptance": "NOT_ASSESSED", "sixty_minute_stability": "NOT_ASSESSED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    run = args.run_dir
    records = [json.loads(line) for line in (run / "runtime-observations.jsonl").read_text().splitlines()]
    result = summarize(config, json.loads((run / "metrics.json").read_text()), records,
                       json.loads((run / "execution.json").read_text())["exit_code"])
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(result["overall"])


if __name__ == "__main__":
    main()
