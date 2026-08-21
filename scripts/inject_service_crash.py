#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROPERTIES = (
    "ActiveState",
    "SubState",
    "MainPID",
    "NRestarts",
    "StatusText",
    "WatchdogTimestampMonotonic",
)


def integer(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def service_state(service: str, state_directory: Path) -> dict[str, Any]:
    command = ["systemctl", "show", service]
    for name in PROPERTIES:
        command.extend(["--property", name])
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    values = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    current = state_directory / "current"
    try:
        session = str(current.resolve(strict=True))
    except (FileNotFoundError, RuntimeError):
        session = None
    return {
        "active_state": values.get("ActiveState"),
        "sub_state": values.get("SubState"),
        "main_pid": integer(values.get("MainPID")),
        "n_restarts": integer(values.get("NRestarts")),
        "status_text": values.get("StatusText"),
        "watchdog_timestamp_monotonic_us": integer(
            values.get("WatchdogTimestampMonotonic")
        ),
        "current_session": session,
    }


def evaluate_recovery(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    failures = []
    if after.get("active_state") != "active" or after.get("sub_state") != "running":
        failures.append("service is not active and running")
    if after.get("status_text") != "video analytics runtime is ready":
        failures.append("service did not report ready")
    if not after.get("main_pid") or after.get("main_pid") == before.get("main_pid"):
        failures.append("main process ID did not change")
    before_restarts = before.get("n_restarts")
    after_restarts = after.get("n_restarts")
    if not isinstance(before_restarts, int) or not isinstance(after_restarts, int):
        failures.append("restart counters are unavailable")
    elif after_restarts <= before_restarts:
        failures.append("automatic restart counter did not increase")
    before_watchdog = before.get("watchdog_timestamp_monotonic_us")
    after_watchdog = after.get("watchdog_timestamp_monotonic_us")
    if not isinstance(after_watchdog, int) or (
        isinstance(before_watchdog, int) and after_watchdog <= before_watchdog
    ):
        failures.append("new process did not make watchdog frame progress")
    if not after.get("current_session") or (
        after.get("current_session") == before.get("current_session")
    ):
        failures.append("new process generation did not create a session")
    return failures


def build_kill_command(service: str, help_text: str) -> list[str]:
    if "--kill-whom=" in help_text:
        selector = "--kill-whom=main"
    elif "--kill-who=" in help_text:
        selector = "--kill-who=main"
    else:
        raise RuntimeError("systemctl does not expose a main-process kill selector")
    return [
        "systemctl",
        "kill",
        selector,
        "--signal=SIGKILL",
        service,
    ]


def give_output_to_invoking_user(path: Path) -> None:
    try:
        uid = int(os.environ["SUDO_UID"])
        gid = int(os.environ["SUDO_GID"])
    except (KeyError, ValueError):
        return
    os.chown(path, uid, gid)
    os.chown(path.parent, uid, gid)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kill the service main process and verify systemd recovery."
    )
    parser.add_argument("--service", default="edge-vision.service")
    parser.add_argument(
        "--state-directory", type=Path, default=Path("/var/lib/edge-vision")
    )
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument(
        "--output", type=Path, default=Path("reports/stability/process_crash.json")
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if os.geteuid() != 0:
        raise SystemExit("run process crash injection with sudo")
    before = service_state(args.service, args.state_directory)
    if before.get("active_state") != "active" or not before.get("main_pid"):
        raise SystemExit("service is not active before fault injection")

    help_result = subprocess.run(
        ["systemctl", "--help"], text=True, capture_output=True, check=False
    )
    command = build_kill_command(
        args.service, help_result.stdout + help_result.stderr
    )
    subprocess.run(command, check=True)

    deadline = time.monotonic() + args.timeout_seconds
    after = service_state(args.service, args.state_directory)
    failures = evaluate_recovery(before, after)
    while failures and time.monotonic() < deadline:
        time.sleep(1)
        after = service_state(args.service, args.state_directory)
        failures = evaluate_recovery(before, after)

    report = {
        "schema_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "fault": "SIGKILL main process",
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "before": before,
        "after": after,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(args.output)
    give_output_to_invoking_user(args.output)
    print(f"status={report['status']}")
    print(f"old_pid={before.get('main_pid')}")
    print(f"new_pid={after.get('main_pid')}")
    print(f"restart_delta={after.get('n_restarts', 0) - before.get('n_restarts', 0)}")
    print(f"report={args.output}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
