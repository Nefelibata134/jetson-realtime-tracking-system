#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FRAME_PATTERN = re.compile(r"(?:^|\s)frame=(\d+)(?:\s|$)")
NUMBER_PATTERN = re.compile(r"^-?\d+(?:\.\d+)?$")
SYSTEMD_PROPERTIES = (
    "ActiveState",
    "SubState",
    "MainPID",
    "NRestarts",
    "StatusText",
    "WatchdogTimestampMonotonic",
    "MemoryCurrent",
    "TasksCurrent",
    "CPUUsageNSec",
    "Result",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n")
    temporary.replace(path)


def parse_systemctl_show(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return values


def integer(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_frame_line(line: str) -> dict[str, Any] | None:
    if FRAME_PATTERN.search(line) is None:
        return None
    record: dict[str, Any] = {}
    for token in line.split():
        key, separator, value = token.partition("=")
        if not separator:
            continue
        if NUMBER_PATTERN.fullmatch(value):
            number = float(value)
            record[key] = int(number) if number.is_integer() else number
        else:
            record[key] = value
    return record if "frame" in record and "e2e_ms" in record else None


class RuntimeLogCursor:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0
        self.device: int | None = None
        self.inode: int | None = None

    def read_frames(self) -> list[dict[str, Any]]:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            self.offset = 0
            self.device = None
            self.inode = None
            return []

        replaced = (self.device, self.inode) != (stat.st_dev, stat.st_ino)
        truncated = stat.st_size < self.offset
        if replaced or truncated:
            self.offset = 0
        self.device, self.inode = stat.st_dev, stat.st_ino

        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            data = stream.read()
            self.offset = stream.tell()

        frames = []
        for line in data.decode(errors="replace").splitlines():
            record = parse_frame_line(line)
            if record is not None:
                frames.append(record)
        return frames


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except FileNotFoundError:
                pass
    return total


def systemd_state(service: str) -> dict[str, Any]:
    command = ["systemctl", "show", service]
    for name in SYSTEMD_PROPERTIES:
        command.extend(["--property", name])
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    values = parse_systemctl_show(result.stdout)
    return {
        "query_exit_code": result.returncode,
        "active_state": values.get("ActiveState"),
        "sub_state": values.get("SubState"),
        "main_pid": integer(values.get("MainPID")),
        "n_restarts": integer(values.get("NRestarts")),
        "status_text": values.get("StatusText"),
        "watchdog_timestamp_monotonic_us": integer(
            values.get("WatchdogTimestampMonotonic")
        ),
        "memory_current_bytes": integer(values.get("MemoryCurrent")),
        "tasks_current": integer(values.get("TasksCurrent")),
        "cpu_usage_ns": integer(values.get("CPUUsageNSec")),
        "result": values.get("Result"),
    }


def current_session(state_directory: Path) -> str | None:
    link = state_directory / "current"
    try:
        return str(link.resolve(strict=True))
    except (FileNotFoundError, RuntimeError):
        return None


def chown_tree(path: Path) -> None:
    uid = integer(os.environ.get("SUDO_UID"))
    gid = integer(os.environ.get("SUDO_GID"))
    if uid is None or gid is None:
        return
    for root, directories, files in os.walk(path):
        os.chown(root, uid, gid)
        for name in directories:
            os.chown(Path(root) / name, uid, gid)
        for name in files:
            os.chown(Path(root) / name, uid, gid)


def chown_path(path: Path) -> None:
    uid = integer(os.environ.get("SUDO_UID"))
    gid = integer(os.environ.get("SUDO_GID"))
    if uid is not None and gid is not None:
        os.chown(path, uid, gid)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sample a supervised edge-vision service during a soak run."
    )
    parser.add_argument("--service", default="edge-vision.service")
    parser.add_argument("--duration-seconds", type=float, default=3600.0)
    parser.add_argument("--sample-interval-seconds", type=float, default=30.0)
    parser.add_argument("--tegrastats-interval-ms", type=int, default=1000)
    parser.add_argument(
        "--output-root", type=Path, default=Path("reports/stability/raw")
    )
    parser.add_argument(
        "--runtime-log", type=Path, default=Path("/var/log/edge-vision/runtime.log")
    )
    parser.add_argument(
        "--state-directory", type=Path, default=Path("/var/lib/edge-vision")
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if os.geteuid() != 0:
        raise SystemExit("run the soak collector with sudo")
    if args.duration_seconds <= 0 or args.sample_interval_seconds <= 0:
        raise SystemExit("duration and sample interval must be positive")
    if args.tegrastats_interval_ms <= 0:
        raise SystemExit("tegrastats interval must be positive")
    if shutil.which("systemctl") is None:
        raise SystemExit("systemctl was not found")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.output_root.mkdir(parents=True, exist_ok=True)
    chown_path(args.output_root)
    run_directory = args.output_root / f"service_soak_{timestamp}_{os.getpid()}"
    run_directory.mkdir(exist_ok=False)
    print(f"run_directory={run_directory}", flush=True)
    samples_path = run_directory / "samples.jsonl"
    telemetry_path = run_directory / "tegrastats.log"
    metadata_path = run_directory / "metadata.json"

    start_monotonic = time.monotonic()
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "service": args.service,
        "start_utc": utc_now(),
        "requested_duration_seconds": args.duration_seconds,
        "sample_interval_seconds": args.sample_interval_seconds,
        "tegrastats_interval_ms": args.tegrastats_interval_ms,
        "runtime_log": str(args.runtime_log),
        "state_directory": str(args.state_directory),
        "completed": False,
        "interrupted": False,
        "sample_count": 0,
    }
    atomic_write_json(metadata_path, metadata)

    telemetry_stream = telemetry_path.open("w")
    telemetry_process: subprocess.Popen[str] | None = None
    tegrastats = shutil.which("tegrastats")
    if tegrastats is not None:
        telemetry_process = subprocess.Popen(
            [tegrastats, "--interval", str(args.tegrastats_interval_ms)],
            stdout=telemetry_stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
    else:
        telemetry_stream.write("tegrastats was not found\n")
        telemetry_stream.flush()

    cursor = RuntimeLogCursor(args.runtime_log)
    deadline = start_monotonic + args.duration_seconds
    next_sample = start_monotonic
    sample_count = 0
    interrupted = False

    try:
        with samples_path.open("a") as samples_stream:
            while True:
                now = time.monotonic()
                if now < next_sample:
                    time.sleep(next_sample - now)
                now = time.monotonic()
                frames = cursor.read_frames()
                disk = shutil.disk_usage(args.state_directory)
                state = systemd_state(args.service)
                sample: dict[str, Any] = {
                    "schema_version": 1,
                    "utc": utc_now(),
                    "elapsed_seconds": now - start_monotonic,
                    "service": state,
                    "current_session": current_session(args.state_directory),
                    "runtime_log_bytes": (
                        args.runtime_log.stat().st_size
                        if args.runtime_log.exists()
                        else None
                    ),
                    "spool_bytes": directory_size(args.state_directory / "spool"),
                    "disk_free_bytes": disk.free,
                    "frame_records_since_sample": len(frames),
                    "latest_frame": frames[-1] if frames else None,
                }
                samples_stream.write(json.dumps(sample, separators=(",", ":")) + "\n")
                samples_stream.flush()
                os.fsync(samples_stream.fileno())
                sample_count += 1

                if now >= deadline:
                    break
                next_sample = min(next_sample + args.sample_interval_seconds, deadline)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        if telemetry_process is not None and telemetry_process.poll() is None:
            telemetry_process.terminate()
            try:
                telemetry_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                telemetry_process.kill()
                telemetry_process.wait()
        telemetry_stream.close()
        metadata.update(
            {
                "end_utc": utc_now(),
                "actual_duration_seconds": time.monotonic() - start_monotonic,
                "completed": not interrupted,
                "interrupted": interrupted,
                "sample_count": sample_count,
                "tegrastats_available": tegrastats is not None,
                "tegrastats_exit_code": (
                    telemetry_process.returncode
                    if telemetry_process is not None
                    else None
                ),
            }
        )
        atomic_write_json(metadata_path, metadata)
        chown_tree(run_directory)

    print(f"samples={sample_count}")
    print(f"interrupted={str(interrupted).lower()}")


if __name__ == "__main__":
    main()
