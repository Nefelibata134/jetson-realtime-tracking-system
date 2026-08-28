#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import statistics
from pathlib import Path
from typing import Iterable


KEY_VALUE_PATTERN = re.compile(r"^([a-zA-Z][a-zA-Z0-9_]*)=(.*)$")
POWER_PATTERN = re.compile(r"VDD_IN (\d+)mW")
GPU_TEMP_PATTERN = re.compile(r"gpu@([\d.]+)C")
TJ_TEMP_PATTERN = re.compile(r"tj@([\d.]+)C")
GPU_UTIL_PATTERN = re.compile(r"GR3D_FREQ (\d+)%")


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = KEY_VALUE_PATTERN.match(line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def trim_samples(
    values: list[float], trim_start: int, trim_end: int
) -> list[float]:
    stop = len(values) - trim_end if trim_end else len(values)
    if trim_start >= stop:
        return values
    return values[trim_start:stop]


def parse_tegrastats(
    text: str, trim_start: int = 3, trim_end: int = 1
) -> dict[str, float | int | None]:
    power: list[float] = []
    gpu_temp: list[float] = []
    tj_temp: list[float] = []
    gpu_util: list[float] = []

    for line in text.splitlines():
        if match := POWER_PATTERN.search(line):
            power.append(float(match.group(1)) / 1000.0)
        if match := GPU_TEMP_PATTERN.search(line):
            gpu_temp.append(float(match.group(1)))
        if match := TJ_TEMP_PATTERN.search(line):
            tj_temp.append(float(match.group(1)))
        if match := GPU_UTIL_PATTERN.search(line):
            gpu_util.append(float(match.group(1)))

    power = trim_samples(power, trim_start, trim_end)
    gpu_temp = trim_samples(gpu_temp, trim_start, trim_end)
    tj_temp = trim_samples(tj_temp, trim_start, trim_end)
    gpu_util = trim_samples(gpu_util, trim_start, trim_end)

    return {
        "telemetry_samples": len(power),
        "power_mean_w": statistics.fmean(power) if power else None,
        "power_p95_w": percentile(power, 0.95),
        "power_max_w": max(power) if power else None,
        "gpu_temp_max_c": max(gpu_temp) if gpu_temp else None,
        "tj_temp_max_c": max(tj_temp) if tj_temp else None,
        "gpu_util_max_percent": max(gpu_util) if gpu_util else None,
    }


def as_float(values: dict[str, str], key: str) -> float | None:
    value = values.get(key)
    return float(value) if value not in (None, "") else None


def as_int(values: dict[str, str], key: str) -> int | None:
    value = values.get(key)
    return int(value) if value not in (None, "") else None


def build_row(
    runtime_path: Path,
    telemetry_path: Path,
    trim_start: int = 3,
    trim_end: int = 1,
) -> dict[str, object]:
    runtime = parse_key_values(runtime_path.read_text(errors="replace"))
    telemetry = parse_tegrastats(
        telemetry_path.read_text(errors="replace"), trim_start, trim_end
    )

    measured = as_int(runtime, "measured_frames")
    dropped = as_int(runtime, "dropped")
    denominator = (measured or 0) + (dropped or 0)
    drop_rate = 100.0 * (dropped or 0) / denominator if denominator else None
    fps = as_float(runtime, "effective_fps")
    power_mean = telemetry["power_mean_w"]
    fps_per_watt = (
        fps / float(power_mean)
        if fps is not None and power_mean not in (None, 0.0)
        else None
    )

    passed = (
        runtime.get("runtime_exit_code") == "0"
        and runtime.get("target_reached") == "true"
        and runtime.get("recovery_exhausted") == "false"
    )
    row: dict[str, object] = {
        "status": "PASS" if passed else "FAIL",
        "timestamp": runtime.get("benchmark_timestamp", ""),
        "model": runtime.get("benchmark_model", ""),
        "resolution": runtime.get("benchmark_resolution", ""),
        "power_mode": runtime.get("power_mode", ""),
        "power_mode_id": runtime.get("power_mode_id", ""),
        "engine_sha256": runtime.get("engine_sha256", ""),
        "measured_frames": measured,
        "dropped": dropped,
        "drop_rate_percent": drop_rate,
        "fps": fps,
        "fps_per_watt": fps_per_watt,
        "inference_mean_ms": as_float(runtime, "inference_mean_ms"),
        "inference_p95_ms": as_float(runtime, "inference_p95_ms"),
        "e2e_mean_ms": as_float(runtime, "end_to_end_mean_ms"),
        "e2e_p95_ms": as_float(runtime, "end_to_end_p95_ms"),
        "runtime_log": runtime_path.name,
        "telemetry_log": telemetry_path.name,
    }
    row.update(telemetry)
    return row


def latest_matrix(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    latest: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows:
        key = (
            str(row["model"]),
            str(row["resolution"]),
            str(row["power_mode_id"]),
        )
        if key not in latest or str(row["timestamp"]) > str(latest[key]["timestamp"]):
            latest[key] = row
    model_order = {"nano": 0, "tiny": 1}
    resolution_order = {"720p": 0, "1080p": 1}
    return sorted(
        latest.values(),
        key=lambda row: (
            model_order.get(str(row["model"]), 99),
            resolution_order.get(str(row["resolution"]), 99),
            str(row["power_mode_id"]),
        ),
    )


CSV_FIELDS = [
    "status",
    "timestamp",
    "model",
    "resolution",
    "power_mode",
    "power_mode_id",
    "engine_sha256",
    "measured_frames",
    "dropped",
    "drop_rate_percent",
    "fps",
    "fps_per_watt",
    "inference_mean_ms",
    "inference_p95_ms",
    "e2e_mean_ms",
    "e2e_p95_ms",
    "telemetry_samples",
    "power_mean_w",
    "power_p95_w",
    "power_max_w",
    "gpu_temp_max_c",
    "tj_temp_max_c",
    "gpu_util_max_percent",
    "runtime_log",
    "telemetry_log",
]


def format_value(value: object, digits: int = 2) -> str:
    if value is None or value == "":
        return "不适用"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, object]]) -> None:
    lines = [
        "# Jetson 检测性能矩阵",
        "",
        "每行使用对应模型、采集分辨率和功率模式的最新一次运行。",
        "功率和温度汇总会排除最前 3 个及最后 1 个遥测样本。",
        "模型输入固定为 416x416；分辨率指 CSI 采集视频流。",
        "",
        "| 状态 | 模型 | 采集 | 功率模式 | FPS | 推理 P95 ms | 端到端 P95 ms | 丢帧率 % | 平均功率 W | FPS/W | GPU 最高温度 C |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {status} | {model} | {resolution} | {power_mode} ({power_mode_id}) | "
            "{fps} | {inference_p95_ms} | {e2e_p95_ms} | {drop_rate_percent} | "
            "{power_mean_w} | {fps_per_watt} | {gpu_temp_max_c} |".format(
                **{key: format_value(value) for key, value in row.items()}
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("reports/benchmarks/raw"))
    parser.add_argument(
        "--csv", type=Path, default=Path("docs/benchmarks/jetson_detection_matrix.csv")
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("docs/benchmarks/jetson_detection_matrix.md"),
    )
    parser.add_argument("--trim-start", type=int, default=3)
    parser.add_argument("--trim-end", type=int, default=1)
    parser.add_argument("--all-runs", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows: list[dict[str, object]] = []
    for runtime_path in sorted(args.input_dir.glob("*.runtime.txt")):
        telemetry_path = runtime_path.with_name(
            runtime_path.name.replace(".runtime.txt", ".tegrastats.txt")
        )
        if not telemetry_path.exists():
            print(f"跳过 {runtime_path}：缺少配套 tegrastats 日志")
            continue
        rows.append(
            build_row(runtime_path, telemetry_path, args.trim_start, args.trim_end)
        )

    if not rows:
        raise SystemExit(f"在 {args.input_dir} 中没有找到完整的基准日志对")
    if not args.all_runs:
        rows = latest_matrix(rows)

    write_csv(args.csv, rows)
    write_markdown(args.markdown, rows)
    print(f"runs={len(rows)}")
    print(f"csv={args.csv}")
    print(f"markdown={args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
