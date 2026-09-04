#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

from caviar_protocol import (
    allows_empty_ground_truth,
    load_json,
    read_ground_truth_frames,
    require_holdout_semantic_audit,
    require_holdout_truth_audit,
    rules_by_pair,
    runtime_rule_arguments,
    sha256_file,
    sequence_by_id,
    validate_dataset_config,
    validate_rules_config,
)


ROOT = Path(__file__).resolve().parents[1]
INPUT_QUEUE_CAPACITY = 8
DEVELOPMENT_SEQUENCES = {"Walk1", "Browse1", "EnterExitCrossingPaths1front"}
THRESHOLD_FIELDS = (
    "score_threshold", "nms_threshold", "track_threshold",
    "new_track_threshold", "match_threshold",
)


def probability(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0 < number <= 1:
        raise argparse.ArgumentTypeError("threshold must be finite and in (0, 1]")
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one frozen CAVIAR event-validation sequence over RTSP"
    )
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--detector", choices=("yolox", "yolo26"), default="yolox")
    for field in THRESHOLD_FIELDS:
        parser.add_argument("--" + field.replace("_", "-"), type=probability)
    parser.add_argument("--track-buffer", type=int)
    parser.add_argument(
        "--binary",
        type=Path,
        default=Path("build/edge_vision_realtime_detect"),
    )
    parser.add_argument(
        "--dataset-config",
        type=Path,
        default=Path("configs/caviar/dataset.json"),
    )
    parser.add_argument("--dataset-root", type=Path, default=Path("data/caviar"))
    parser.add_argument(
        "--output-root", type=Path, default=Path("outputs/caviar/external")
    )
    parser.add_argument("--rtsp-port", type=int, default=8554)
    parser.add_argument("--allow-holdout", action="store_true")
    return parser.parse_args(argv)


def resolve_runtime(args: argparse.Namespace, sequence: dict, frozen: dict) -> dict:
    fields = (*THRESHOLD_FIELDS, "track_buffer")
    overrides = {
        field: getattr(args, field) for field in fields
        if getattr(args, field) is not None
    }
    if args.detector == "yolo26" or overrides:
        if (
            sequence["split"] != "development"
            or sequence["sequence_id"] not in DEVELOPMENT_SEQUENCES
        ):
            raise ValueError(
                "candidate or overridden parameters are development-only; holdout is blocked"
            )
    if args.detector == "yolo26":
        missing = [field for field in THRESHOLD_FIELDS if field not in overrides]
        if missing:
            raise ValueError("YOLO26 requires explicit thresholds: " + ", ".join(missing))

    runtime = dict(frozen)
    # The legacy command omits match-threshold and uses the C++ default 0.8.
    runtime["match_threshold"] = 0.8
    runtime.update(overrides)
    for field in THRESHOLD_FIELDS:
        value = runtime.get(field)
        if (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 < value <= 1
        ):
            raise ValueError(f"{field} must be finite and in (0, 1]")
    if not (
        runtime["score_threshold"] < runtime["track_threshold"]
        <= runtime["new_track_threshold"]
    ):
        raise ValueError("require score < track <= new-track")
    buffer = runtime.get("track_buffer")
    if isinstance(buffer, bool) or not isinstance(buffer, int) or buffer <= 0:
        raise ValueError("track-buffer must be a positive integer")
    return runtime


def detector_runtime_arguments(args: argparse.Namespace, runtime: dict) -> list[str]:
    result = ["--detector", "yolo26"] if args.detector == "yolo26" else []
    for field in THRESHOLD_FIELDS:
        if (
            field == "match_threshold" and args.detector == "yolox"
            and args.match_threshold is None
        ):
            continue
        result.extend(["--" + field.replace("_", "-"), str(runtime[field])])
    return result + ["--track-buffer", str(runtime["track_buffer"])]


def require_complete_frames(metrics: dict, expected_frames: int) -> None:
    if metrics.get("schema_version") != 1 or metrics.get("source") != "rtsp":
        raise ValueError("invalid measurement: expected schema 1 RTSP metrics")
    status = metrics.get("status", {})
    pipeline = metrics.get("pipeline", {})
    if not isinstance(status, dict) or not isinstance(pipeline, dict):
        raise ValueError("invalid measurement: missing status or pipeline object")
    checks = {
        "processed_frames": expected_frames, "measured_frames": expected_frames,
        "target_frames": expected_frames, "warmup_frames": 0,
        "dropped_frames_total": 0, "dropped_frames": 0, "warmup_dropped_frames": 0,
        "sequence_gaps": 0, "restart_attempts": 0, "restart_successes": 0,
    }
    if (
        status.get("target_reached") is not True
        or type(status.get("invalid_frames")) is not int or status["invalid_frames"] != 0
    ):
        raise ValueError("invalid measurement: incomplete target or invalid frames")
    for field, expected in checks.items():
        if type(pipeline.get(field)) is not int or pipeline[field] != expected:
            raise ValueError(f"invalid measurement: {field} must equal {expected}")


def write_manifest(
    directory: Path, args: argparse.Namespace, sequence: dict,
    runtime: dict, files: dict[str, Path],
) -> None:
    commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain"], text=True
    ).strip()
    manifest = {
        "schema_version": 1, "source_commit": commit, "source_tree_dirty": bool(dirty),
        "detector": args.detector, "sequence": sequence["sequence_id"],
        "split": sequence["split"], "runtime_policy": runtime,
        "input_queue_capacity": INPUT_QUEUE_CAPACITY,
        "files": {
            name: {"path": str(path), "sha256": sha256_file(path)}
            for name, path in files.items()
        },
    }
    with (directory / "run-manifest.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def require_inactive_service() -> None:
    if shutil.which("systemctl") is None:
        return
    result = subprocess.run(
        ["systemctl", "is-active", "edge-vision.service"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.stdout.strip() == "active":
        raise ValueError(
            "edge-vision.service is active; stop it before controlled validation"
        )


def run_and_log(command: list[str], log_path: Path) -> int:
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log.write(line)
        return process.wait()


def main() -> int:
    args = parse_args()
    rtsp_server: subprocess.Popen[str] | None = None
    server_log_handle = None
    run_directory: Path | None = None
    try:
        if not 1 <= args.rtsp_port <= 65535:
            raise ValueError("rtsp-port must be between 1 and 65535")
        dataset_config = load_json(args.dataset_config)
        validate_dataset_config(dataset_config)
        rules_config = load_json(args.rules)
        validate_rules_config(rules_config, dataset_config, require_frozen=True)
        sequence = sequence_by_id(dataset_config, args.sequence)
        runtime = resolve_runtime(args, sequence, rules_config["runtime_policy"])
        require_holdout_semantic_audit(dataset_config, sequence)
        require_holdout_truth_audit(dataset_config, sequence)
        if sequence["split"] == "holdout" and not args.allow_holdout:
            raise ValueError(
                "holdout execution requires the explicit --allow-holdout flag"
            )
        require_inactive_service()
        if not args.binary.is_file():
            raise ValueError(f"runtime binary does not exist: {args.binary}")
        if not args.engine.is_file():
            raise ValueError(f"TensorRT engine does not exist: {args.engine}")
        prepared_video = (
            args.dataset_root / "prepared" / "videos" / f"{sequence['sequence_id']}.mp4"
        )
        if not prepared_video.is_file() or prepared_video.stat().st_size == 0:
            raise ValueError(
                f"prepared H.264 video is missing: {prepared_video}; "
                "run scripts/prepare_caviar_media.py first"
            )

        dataset = dataset_config["dataset"]
        annotation = args.dataset_root / sequence["annotation"]["relative_path"]
        if sha256_file(annotation) != sequence["annotation"]["sha256"]:
            raise ValueError("annotation SHA-256 does not match the frozen dataset")
        xml_name, frames = read_ground_truth_frames(
            annotation,
            frame_width=dataset["frame_width"],
            frame_height=dataset["frame_height"],
        )
        if xml_name != sequence["sequence_id"]:
            raise ValueError("annotation sequence name does not match the protocol")

        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_directory = args.output_root / f"{sequence['sequence_id']}-{timestamp}"
        run_directory.mkdir(parents=True)
        snapshots = run_directory / "snapshots"
        clips = run_directory / "clips"
        snapshots.mkdir()
        clips.mkdir()
        expected_path = run_directory / "expected-events.jsonl"
        expected_markdown = run_directory / "expected-events.md"
        actual_path = run_directory / "events.jsonl"
        report_json = run_directory / "report.json"
        report_markdown = run_directory / "report.md"
        write_manifest(run_directory, args, sequence, runtime, {
            "engine": args.engine, "binary": args.binary,
            "dataset_config": args.dataset_config, "rules": args.rules,
            "prepared_video": prepared_video, "annotation": annotation,
            "runner": Path(__file__), "protocol": ROOT / "scripts" / "caviar_protocol.py",
            "truth_generator": ROOT / "scripts" / "generate_caviar_ground_truth.py",
            "evaluator": ROOT / "scripts" / "evaluate_caviar_events.py",
        })

        generator = [
            sys.executable,
            str(ROOT / "scripts" / "generate_caviar_ground_truth.py"),
            "--dataset-config",
            str(args.dataset_config),
            "--rules",
            str(args.rules),
            "--dataset-root",
            str(args.dataset_root),
            "--sequence",
            sequence["sequence_id"],
            "--output",
            str(expected_path),
            "--output-markdown",
            str(expected_markdown),
        ]
        subprocess.run(generator, check=True)
        if expected_path.stat().st_size == 0 and not allows_empty_ground_truth(
            sequence
        ):
            raise ValueError("the frozen rule produced no positive ground-truth events")

        rule = rules_by_pair(rules_config)[sequence["pair_id"]]
        mount = "/caviar"
        rtsp_uri = f"rtsp://127.0.0.1:{args.rtsp_port}{mount}"
        server_log_handle = (run_directory / "rtsp-server.log").open(
            "w", encoding="utf-8", newline="\n"
        )
        rtsp_server = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "scripts" / "serve_rtsp_replay.py"),
                str(prepared_video),
                "--port",
                str(args.rtsp_port),
                "--mount",
                mount,
            ],
            stdout=server_log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(2)
        if rtsp_server.poll() is not None:
            raise ValueError("the local RTSP replay server exited during startup")

        command = [
            str(args.binary),
            "--engine",
            str(args.engine),
            "--rtsp",
            rtsp_uri,
            "--rtsp-transport",
            "tcp",
            "--rtsp-latency-ms",
            "200",
            "--rtsp-timeout-ms",
            "5000",
            "--width",
            str(dataset["frame_width"]),
            "--height",
            str(dataset["frame_height"]),
            "--fps",
            str(dataset["frames_per_second"]),
            "--warmup-frames",
            "0",
            "--frames",
            str(len(frames)),
            "--queue-capacity",
            str(INPUT_QUEUE_CAPACITY),
            *detector_runtime_arguments(args, runtime),
            *runtime_rule_arguments(rule),
            "--event-class-id",
            str(runtime["event_class_id"]),
            "--event-jsonl",
            str(actual_path),
            "--event-snapshot-dir",
            str(snapshots),
            "--event-clip-dir",
            str(clips),
            "--event-clip-pre-seconds",
            "1",
            "--event-clip-post-seconds",
            "1",
            "--output-video",
            str(run_directory / "annotated.mp4"),
            "--output-encoder",
            "x264",
            "--output-bitrate-kbps",
            "2500",
            "--output-queue-capacity",
            "4",
            "--metrics-json",
            str(run_directory / "metrics.json"),
            "--tegrastats-interval-ms",
            "500",
            "--log-interval",
            "250",
            "--reconnect-attempts",
            "0",
        ]
        (run_directory / "run-command.json").write_text(
            json.dumps(command, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        runtime_status = run_and_log(command, run_directory / "runtime.log")
        if runtime_status != 0:
            raise ValueError(f"runtime exited with status {runtime_status}")
        require_complete_frames(load_json(run_directory / "metrics.json"), len(frames))

        evaluator = [
            sys.executable,
            str(ROOT / "scripts" / "evaluate_caviar_events.py"),
            "--dataset-config",
            str(args.dataset_config),
            "--rules",
            str(args.rules),
            "--sequence",
            sequence["sequence_id"],
            "--expected",
            str(expected_path),
            "--actual",
            str(actual_path),
            "--evidence-root",
            ".",
            "--output-json",
            str(report_json),
            "--output-markdown",
            str(report_markdown),
        ]
        evaluation = subprocess.run(evaluator, check=False)
        if evaluation.returncode != 0:
            print(f"run_directory={run_directory}")
            return evaluation.returncode
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"CAVIAR external validation failed: {error}")
        if run_directory is not None:
            print(f"run_directory={run_directory}; invalid or failed run retained")
        return 1
    finally:
        if rtsp_server is not None and rtsp_server.poll() is None:
            rtsp_server.terminate()
            try:
                rtsp_server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                rtsp_server.kill()
                rtsp_server.wait(timeout=5)
        if server_log_handle is not None:
            server_log_handle.close()

    print(f"run_directory={run_directory}")
    print("status=COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
