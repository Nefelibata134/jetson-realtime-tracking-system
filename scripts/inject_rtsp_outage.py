#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_key_values(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key.replace("_", "").isalnum():
            values[key] = value
    return values


def integer(values: dict[str, str], key: str) -> int | None:
    try:
        return int(values[key])
    except (KeyError, ValueError):
        return None


def evaluate_rtsp_recovery(values: dict[str, str], exit_code: int) -> list[str]:
    failures = []
    if exit_code != 0:
        failures.append(f"runtime exited with code {exit_code}")
    if values.get("target_reached") != "true":
        failures.append("runtime did not reach the requested frame target")
    if values.get("recovery_exhausted") != "false":
        failures.append("runtime exhausted source recovery")
    for key in ("restart_successes", "stream_generation", "tracker_resets"):
        value = integer(values, key)
        if value is None or value < 1:
            failures.append(f"{key} did not record a real-frame recovery")
    return failures


def wait_for_port(port: int, process: subprocess.Popen[str], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("RTSP replay server exited before accepting connections")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("RTSP replay server did not open its TCP port")


def stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interrupt a local RTSP replay and verify real-frame recovery."
    )
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument(
        "--binary",
        type=Path,
        default=Path("build-stability/edge_vision_realtime_detect"),
    )
    parser.add_argument("--port", type=int, default=8554)
    parser.add_argument("--mount", default="/replay")
    parser.add_argument("--warmup-frames", type=int, default=30)
    parser.add_argument("--frames", type=int, default=180)
    parser.add_argument("--outage-after-seconds", type=float, default=3.0)
    parser.add_argument("--outage-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument(
        "--output-root", type=Path, default=Path("reports/stability/raw")
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path, label in (
        (args.video, "video"),
        (args.engine, "engine"),
        (args.binary, "runtime binary"),
    ):
        if not path.is_file():
            raise SystemExit(f"{label} does not exist: {path}")
    if args.frames <= 0 or args.warmup_frames < 0:
        raise SystemExit("frame counts are invalid")
    if args.outage_after_seconds <= 0 or args.outage_seconds <= 0:
        raise SystemExit("outage timings must be positive")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_directory = args.output_root / f"rtsp_outage_{timestamp}_{os.getpid()}"
    run_directory.mkdir(parents=True, exist_ok=False)
    server_log_path = run_directory / "server.log"
    runtime_log_path = run_directory / "runtime.log"
    metrics_path = run_directory / "metrics.json"
    report_path = run_directory / "report.json"
    server_script = Path(__file__).with_name("serve_rtsp_replay.py")
    server_command = [
        sys.executable,
        str(server_script),
        str(args.video.resolve()),
        "--port",
        str(args.port),
        "--mount",
        args.mount,
    ]
    runtime_command = [
        str(args.binary.resolve()),
        "--engine",
        str(args.engine.resolve()),
        "--rtsp",
        f"rtsp://127.0.0.1:{args.port}{args.mount}",
        "--rtsp-transport",
        "tcp",
        "--rtsp-latency-ms",
        "100",
        "--rtsp-timeout-ms",
        "1000",
        "--width",
        "1280",
        "--height",
        "720",
        "--fps",
        "30",
        "--warmup-frames",
        str(args.warmup_frames),
        "--frames",
        str(args.frames),
        "--queue-capacity",
        "2",
        "--score-threshold",
        "0.3",
        "--track-threshold",
        "0.5",
        "--new-track-threshold",
        "0.6",
        "--track-buffer",
        "30",
        "--reconnect-attempts",
        "8",
        "--reconnect-delay-ms",
        "500",
        "--log-interval",
        "30",
        "--metrics-json",
        str(metrics_path.resolve()),
    ]

    server: subprocess.Popen[str] | None = None
    runtime: subprocess.Popen[str] | None = None
    runtime_text = ""
    server_stream = server_log_path.open("a")
    try:
        server = subprocess.Popen(
            server_command,
            stdout=server_stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
        wait_for_port(args.port, server, 10.0)
        runtime = subprocess.Popen(
            runtime_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(args.outage_after_seconds)
        stop_process(server)
        server = None
        time.sleep(args.outage_seconds)
        server = subprocess.Popen(
            server_command,
            stdout=server_stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
        wait_for_port(args.port, server, 10.0)
        runtime_text, _ = runtime.communicate(timeout=args.timeout_seconds)
    except subprocess.TimeoutExpired:
        if runtime is not None:
            runtime.kill()
            runtime_text, _ = runtime.communicate()
        runtime_text += "\nfault_injection_error=runtime timeout\n"
    finally:
        stop_process(server)
        stop_process(runtime)
        server_stream.close()

    runtime_log_path.write_text(runtime_text)
    exit_code = runtime.returncode if runtime is not None else 1
    if exit_code is None:
        exit_code = 1
    values = parse_key_values(runtime_text)
    failures = evaluate_rtsp_recovery(values, exit_code)
    report: dict[str, Any] = {
        "schema_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "fault": "local RTSP server outage",
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "outage_after_seconds": args.outage_after_seconds,
        "outage_seconds": args.outage_seconds,
        "runtime_exit_code": exit_code,
        "target_reached": values.get("target_reached"),
        "restart_attempts": integer(values, "restart_attempts"),
        "restart_successes": integer(values, "restart_successes"),
        "stream_generation": integer(values, "stream_generation"),
        "tracker_resets": integer(values, "tracker_resets"),
        "recovery_exhausted": values.get("recovery_exhausted"),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(runtime_text, end="")
    print(f"fault_status={report['status']}")
    print(f"fault_report={report_path}")
    if failures:
        raise SystemExit(1)
if __name__ == "__main__":
    main()
