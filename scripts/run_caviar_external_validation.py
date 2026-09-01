#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
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
    sequence_by_id,
    validate_dataset_config,
    validate_rules_config,
)


ROOT = Path(__file__).resolve().parents[1]
INPUT_QUEUE_CAPACITY = 8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one frozen CAVIAR event-validation sequence over RTSP"
    )
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
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
    return parser.parse_args()


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
    try:
        require_inactive_service()
        if not 1 <= args.rtsp_port <= 65535:
            raise ValueError("rtsp-port must be between 1 and 65535")
        dataset_config = load_json(args.dataset_config)
        validate_dataset_config(dataset_config)
        rules_config = load_json(args.rules)
        validate_rules_config(rules_config, dataset_config, require_frozen=True)
        sequence = sequence_by_id(dataset_config, args.sequence)
        require_holdout_semantic_audit(dataset_config, sequence)
        require_holdout_truth_audit(dataset_config, sequence)
        if sequence["split"] == "holdout" and not args.allow_holdout:
            raise ValueError(
                "holdout execution requires the explicit --allow-holdout flag"
            )
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
        xml_name, frames = read_ground_truth_frames(
            annotation,
            frame_width=dataset["frame_width"],
            frame_height=dataset["frame_height"],
        )
        if xml_name != sequence["sequence_id"]:
            raise ValueError("annotation sequence name does not match the protocol")

        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_directory = args.output_root / f"{sequence['sequence_id']}-{timestamp}"
        snapshots = run_directory / "snapshots"
        clips = run_directory / "clips"
        snapshots.mkdir(parents=True)
        clips.mkdir()
        expected_path = run_directory / "expected-events.jsonl"
        expected_markdown = run_directory / "expected-events.md"
        actual_path = run_directory / "events.jsonl"
        report_json = run_directory / "report.json"
        report_markdown = run_directory / "report.md"

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
        runtime = rules_config["runtime_policy"]
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
            "--score-threshold",
            str(runtime["score_threshold"]),
            "--nms-threshold",
            str(runtime["nms_threshold"]),
            "--track-threshold",
            str(runtime["track_threshold"]),
            "--new-track-threshold",
            str(runtime["new_track_threshold"]),
            "--track-buffer",
            str(runtime["track_buffer"]),
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
