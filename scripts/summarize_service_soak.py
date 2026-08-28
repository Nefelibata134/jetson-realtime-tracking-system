#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


POWER_PATTERN = re.compile(r"VDD_IN\s+(\d+)mW")
GPU_PATTERN = re.compile(r"GR3D_FREQ\s+(\d+)%")
GPU_TEMP_PATTERN = re.compile(r"gpu@([\d.]+)C")
TJ_TEMP_PATTERN = re.compile(r"tj@([\d.]+)C")


def percentile(values: Iterable[float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def numeric_summary(values: Iterable[float]) -> dict[str, float | int | None]:
    data = [float(value) for value in values]
    return {
        "samples": len(data),
        "mean": mean(data) if data else None,
        "p95": percentile(data, 0.95),
        "max": max(data) if data else None,
    }


def linear_slope_per_minute(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    x_mean = mean(point[0] for point in points)
    y_mean = mean(point[1] for point in points)
    denominator = sum((x - x_mean) ** 2 for x, _ in points)
    if denominator == 0:
        return None
    slope_per_second = sum(
        (x - x_mean) * (y - y_mean) for x, y in points
    ) / denominator
    return slope_per_second * 60.0


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON at {path}:{line_number}: {error}") from error
    return records


def parse_tegrastats(path: Path) -> dict[str, dict[str, float | int | None]]:
    power: list[float] = []
    gpu: list[float] = []
    gpu_temp: list[float] = []
    tj_temp: list[float] = []
    if path.is_file():
        for line in path.read_text(errors="replace").splitlines():
            if match := POWER_PATTERN.search(line):
                power.append(float(match.group(1)) / 1000.0)
            if match := GPU_PATTERN.search(line):
                gpu.append(float(match.group(1)))
            if match := GPU_TEMP_PATTERN.search(line):
                gpu_temp.append(float(match.group(1)))
            if match := TJ_TEMP_PATTERN.search(line):
                tj_temp.append(float(match.group(1)))
    return {
        "input_power_w": numeric_summary(power),
        "gpu_utilization_percent": numeric_summary(gpu),
        "gpu_temperature_c": numeric_summary(gpu_temp),
        "junction_temperature_c": numeric_summary(tj_temp),
    }


def nested(document: dict[str, Any] | None, *keys: str) -> Any:
    value: Any = document
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def unique_changes(values: list[Any]) -> int:
    compact = [value for value in values if value not in (None, 0, "")]
    return sum(left != right for left, right in zip(compact, compact[1:]))


def build_summary(
    run_directory: Path,
    *,
    min_coverage: float = 0.98,
    max_temperature_c: float = 85.0,
    min_disk_free_bytes: int = 1024**3,
    max_memory_growth_mib: float = 256.0,
    max_memory_slope_mib_per_minute: float = 2.0,
    min_fps: float = 25.0,
    max_drop_rate_percent: float = 1.0,
) -> dict[str, Any]:
    metadata = json.loads((run_directory / "metadata.json").read_text())
    samples = load_jsonl(run_directory / "samples.jsonl")
    telemetry = parse_tegrastats(run_directory / "tegrastats.log")
    final_path = run_directory / "final_metrics.json"
    final_metrics = json.loads(final_path.read_text()) if final_path.is_file() else None

    requested_duration = float(metadata.get("requested_duration_seconds", 0.0))
    observed_duration = (
        float(samples[-1]["elapsed_seconds"]) - float(samples[0]["elapsed_seconds"])
        if len(samples) >= 2
        else 0.0
    )
    coverage = observed_duration / requested_duration if requested_duration > 0 else 0.0
    services = [sample.get("service", {}) for sample in samples]
    active_samples = sum(
        state.get("active_state") == "active" and state.get("sub_state") == "running"
        for state in services
    )
    active_ratio = active_samples / len(samples) if samples else 0.0
    pids = [state.get("main_pid") for state in services]
    restarts = [
        state.get("n_restarts")
        for state in services
        if isinstance(state.get("n_restarts"), int)
    ]
    restart_delta = restarts[-1] - restarts[0] if restarts else None

    watchdog_stalls = 0
    for previous, current in zip(services, services[1:]):
        previous_value = previous.get("watchdog_timestamp_monotonic_us")
        current_value = current.get("watchdog_timestamp_monotonic_us")
        if (
            previous.get("main_pid") == current.get("main_pid")
            and previous_value not in (None, 0)
            and current_value == previous_value
        ):
            watchdog_stalls += 1
    frame_stalls = sum(
        int(sample.get("frame_records_since_sample", 0)) == 0
        for sample in samples[1:]
    )

    memory_points = [
        (float(sample["elapsed_seconds"]), float(state["memory_current_bytes"]) / 1024**2)
        for sample, state in zip(samples, services)
        if isinstance(state.get("memory_current_bytes"), int)
    ]
    observed_end = memory_points[-1][0] if memory_points else 0.0
    warmup_end = min(300.0, observed_end * 0.2)
    steady_memory = [point for point in memory_points if point[0] >= warmup_end]
    memory_growth = (
        steady_memory[-1][1] - steady_memory[0][1]
        if len(steady_memory) >= 2
        else None
    )
    memory_slope = linear_slope_per_minute(steady_memory)
    disk_values = [
        int(sample["disk_free_bytes"])
        for sample in samples
        if isinstance(sample.get("disk_free_bytes"), int)
    ]
    spool_values = [
        int(sample["spool_bytes"])
        for sample in samples
        if isinstance(sample.get("spool_bytes"), int)
    ]
    latest_frames = [
        sample["latest_frame"]
        for sample in samples
        if isinstance(sample.get("latest_frame"), dict)
    ]
    sampled_inference = [
        float(frame["infer_ms"])
        for frame in latest_frames
        if isinstance(frame.get("infer_ms"), (int, float))
    ]
    sampled_e2e = [
        float(frame["e2e_ms"])
        for frame in latest_frames
        if isinstance(frame.get("e2e_ms"), (int, float))
    ]

    failures: list[str] = []
    if len(samples) < 2:
        failures.append("服务样本少于 2 个")
    if metadata.get("completed") is not True:
        failures.append("采集器未正常完成")
    if coverage < min_coverage:
        failures.append(f"时长覆盖率 {coverage:.3f} 低于 {min_coverage:.3f}")
    if active_ratio < 1.0:
        failures.append(f"服务活跃率 {active_ratio:.3f} 低于 1.000")
    if unique_changes(pids) != 0:
        failures.append("基线持续运行期间主进程发生变化")
    if restart_delta not in (0, None):
        failures.append(f"自动重启计数增加了 {restart_delta}")
    if watchdog_stalls:
        failures.append(f"watchdog 进度在 {watchdog_stalls} 个采样窗口中停滞")
    if frame_stalls:
        failures.append(f"运行帧记录在 {frame_stalls} 个采样窗口中停滞")
    maximum_temperature = max(
        value
        for value in (
            telemetry["gpu_temperature_c"]["max"],
            telemetry["junction_temperature_c"]["max"],
        )
        if value is not None
    ) if any(
        value is not None
        for value in (
            telemetry["gpu_temperature_c"]["max"],
            telemetry["junction_temperature_c"]["max"],
        )
    ) else None
    if maximum_temperature is None:
        failures.append("tegrastats 温度样本不可用")
    elif maximum_temperature > max_temperature_c:
        failures.append(
            f"最高温度 {maximum_temperature:.2f} C 超过 {max_temperature_c:.2f} C"
        )
    if not disk_values:
        failures.append("可用磁盘空间样本不可用")
    elif min(disk_values) < min_disk_free_bytes:
        failures.append("最小可用磁盘空间低于配置门限")
    if memory_growth is None or memory_slope is None:
        failures.append("服务内存样本不足")
    else:
        if memory_growth > max_memory_growth_mib:
            failures.append(
                f"稳态内存增长 {memory_growth:.2f} MiB，超过 {max_memory_growth_mib:.2f} MiB"
            )
        if memory_slope > max_memory_slope_mib_per_minute:
            failures.append(
                f"内存斜率 {memory_slope:.3f} MiB/min 超过 {max_memory_slope_mib_per_minute:.3f}"
            )
    if final_metrics is None:
        failures.append("缺少最终运行指标")
    else:
        if nested(final_metrics, "status", "shutdown_requested") is not True:
            failures.append("运行时没有记录有序停止请求")
        if nested(final_metrics, "status", "shutdown_signal") != 15:
            failures.append("运行时停止信号不是 SIGTERM (15)")
        if nested(final_metrics, "status", "invalid_frames") != 0:
            failures.append("运行时报告了无效帧")
        if nested(final_metrics, "status", "recovery_exhausted") is not False:
            failures.append("运行时耗尽输入源恢复次数")
        fps = nested(final_metrics, "pipeline", "effective_fps")
        drop_rate = nested(final_metrics, "pipeline", "drop_rate_percent")
        if not isinstance(fps, (int, float)) or fps < min_fps:
            failures.append(f"有效 FPS 低于 {min_fps:.2f}")
        if not isinstance(drop_rate, (int, float)) or drop_rate > max_drop_rate_percent:
            failures.append(f"丢帧率超过 {max_drop_rate_percent:.2f}%")

    final_fps = nested(final_metrics, "pipeline", "effective_fps")
    final_frames = nested(final_metrics, "pipeline", "measured_frames")
    generation_seconds = (
        float(final_frames) / float(final_fps)
        if isinstance(final_frames, (int, float))
        and isinstance(final_fps, (int, float))
        and final_fps > 0
        else None
    )
    generation_to_soak_ratio = (
        generation_seconds / observed_duration
        if generation_seconds is not None and observed_duration > 0
        else None
    )
    notes = []
    if generation_to_soak_ratio is not None and not 0.9 <= generation_to_soak_ratio <= 1.1:
        notes.append(
            "最终运行指标与持续运行采样覆盖不同的进程代次窗口；若需对齐窗口，"
            "应在采集前立即重启，并在采集结束后尽快完成收尾"
        )

    return {
        "schema_version": 1,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "notes": notes,
        "run_directory": str(run_directory),
        "duration": {
            "requested_seconds": requested_duration,
            "observed_seconds": observed_duration,
            "coverage": coverage,
            "samples": len(samples),
        },
        "service": {
            "active_ratio": active_ratio,
            "pid_changes": unique_changes(pids),
            "restart_delta": restart_delta,
            "watchdog_stall_windows": watchdog_stalls,
            "frame_stall_windows": frame_stalls,
            "first_pid": next((pid for pid in pids if pid), None),
            "last_pid": next((pid for pid in reversed(pids) if pid), None),
        },
        "resources": {
            "memory_start_mib": memory_points[0][1] if memory_points else None,
            "memory_end_mib": memory_points[-1][1] if memory_points else None,
            "memory_max_mib": max((point[1] for point in memory_points), default=None),
            "steady_memory_growth_mib": memory_growth,
            "steady_memory_slope_mib_per_minute": memory_slope,
            "disk_free_min_gib": min(disk_values) / 1024**3 if disk_values else None,
            "spool_growth_mib": (
                (spool_values[-1] - spool_values[0]) / 1024**2
                if len(spool_values) >= 2
                else None
            ),
        },
        "sampled_runtime": {
            "inference_ms": numeric_summary(sampled_inference),
            "end_to_end_ms": numeric_summary(sampled_e2e),
        },
        "tegrastats": telemetry,
        "final_runtime_metrics": {
            "available": final_metrics is not None,
            "effective_fps": final_fps,
            "drop_rate_percent": nested(
                final_metrics, "pipeline", "drop_rate_percent"
            ),
            "measured_frames": final_frames,
            "estimated_generation_seconds": generation_seconds,
            "generation_to_soak_ratio": generation_to_soak_ratio,
            "inference_p95_ms": nested(
                final_metrics, "latency_ms", "tensorrt_inference", "p95"
            ),
            "end_to_end_p95_ms": nested(
                final_metrics, "latency_ms", "end_to_end", "p95"
            ),
        },
        "thresholds": {
            "min_coverage": min_coverage,
            "max_temperature_c": max_temperature_c,
            "min_disk_free_bytes": min_disk_free_bytes,
            "max_memory_growth_mib": max_memory_growth_mib,
            "max_memory_slope_mib_per_minute": max_memory_slope_mib_per_minute,
            "min_fps": min_fps,
            "max_drop_rate_percent": max_drop_rate_percent,
        },
    }


def number(value: Any, digits: int = 2, suffix: str = "") -> str:
    return "不适用" if value is None else f"{float(value):.{digits}f}{suffix}"


def markdown(summary: dict[str, Any]) -> str:
    duration = summary["duration"]
    service = summary["service"]
    resources = summary["resources"]
    telemetry = summary["tegrastats"]
    final = summary["final_runtime_metrics"]
    lines = [
        "# 服务稳定性与恢复报告",
        "",
        f"**状态：{summary['status']}**",
        "",
        "## 持续运行结果",
        "",
        "| 观测时长 | 覆盖率 | 样本数 | 活跃率 | PID 变化 | 重启 | Watchdog 停滞 | 帧停滞 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        "| {observed} min | {coverage}% | {samples} | {active}% | {pid_changes} | {restarts} | {watchdog} | {frames} |".format(
            observed=number(duration["observed_seconds"] / 60.0),
            coverage=number(duration["coverage"] * 100.0),
            samples=duration["samples"],
            active=number(service["active_ratio"] * 100.0),
            pid_changes=service["pid_changes"],
            restarts=service["restart_delta"],
            watchdog=service["watchdog_stall_windows"],
            frames=service["frame_stall_windows"],
        ),
        "",
        "## 资源趋势",
        "",
        "| RAM 起始 | RAM 峰值 | RAM 结束 | 稳态增长 | 斜率 | Spool 增长 | 最小可用磁盘 | 平均功率 | GPU/TJ 最高温度 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        "| {start} | {maximum} | {end} | {growth} | {slope} | {spool} | {disk} | {power} | {temperature} |".format(
            start=number(resources["memory_start_mib"], suffix=" MiB"),
            maximum=number(resources["memory_max_mib"], suffix=" MiB"),
            end=number(resources["memory_end_mib"], suffix=" MiB"),
            growth=number(resources["steady_memory_growth_mib"], suffix=" MiB"),
            slope=number(
                resources["steady_memory_slope_mib_per_minute"], 3, " MiB/min"
            ),
            spool=number(resources["spool_growth_mib"], suffix=" MiB"),
            disk=number(resources["disk_free_min_gib"], suffix=" GiB"),
            power=number(telemetry["input_power_w"]["mean"], suffix=" W"),
            temperature=number(
                max(
                    value
                    for value in (
                        telemetry["gpu_temperature_c"]["max"],
                        telemetry["junction_temperature_c"]["max"],
                    )
                    if value is not None
                )
                if any(
                    value is not None
                    for value in (
                        telemetry["gpu_temperature_c"]["max"],
                        telemetry["junction_temperature_c"]["max"],
                    )
                )
                else None,
                suffix=" C",
            ),
        ),
        "",
        "## 最终运行指标",
        "",
        "| 帧数 | 估算代次时长 | FPS | 丢帧率 % | TRT P95 | 端到端 P95 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        "| {frames} | {generation} min | {fps} | {drop} | {trt} ms | {e2e} ms |".format(
            frames=final["measured_frames"],
            generation=number(final["estimated_generation_seconds"] / 60.0)
            if final["estimated_generation_seconds"] is not None
            else "不适用",
            fps=number(final["effective_fps"]),
            drop=number(final["drop_rate_percent"]),
            trt=number(final["inference_p95_ms"]),
            e2e=number(final["end_to_end_p95_ms"]),
        ),
        "",
        "最终指标由运行时在 SIGTERM 有序停止后生成。实时样本使用 systemd 状态、"
        "watchdog 进度和行缓冲帧记录。",
        "",
    ]
    if summary["notes"]:
        lines.extend(["## 说明", ""])
        lines.extend(f"- {note}" for note in summary["notes"])
        lines.append("")
    if summary["failures"]:
        lines.extend(["## 未通过检查", ""])
        lines.extend(f"- {failure}" for failure in summary["failures"])
        lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--max-temperature-c", type=float, default=85.0)
    parser.add_argument("--min-disk-free-gib", type=float, default=1.0)
    parser.add_argument("--max-memory-growth-mib", type=float, default=256.0)
    parser.add_argument(
        "--max-memory-slope-mib-per-minute", type=float, default=2.0
    )
    parser.add_argument("--min-fps", type=float, default=25.0)
    parser.add_argument("--max-drop-rate-percent", type=float, default=1.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_summary(
        args.run_dir,
        max_temperature_c=args.max_temperature_c,
        min_disk_free_bytes=int(args.min_disk_free_gib * 1024**3),
        max_memory_growth_mib=args.max_memory_growth_mib,
        max_memory_slope_mib_per_minute=args.max_memory_slope_mib_per_minute,
        min_fps=args.min_fps,
        max_drop_rate_percent=args.max_drop_rate_percent,
    )
    json_path = args.run_dir / "summary.json"
    markdown_path = args.run_dir / "report.md"
    json_path.write_text(json.dumps(summary, indent=2) + "\n")
    markdown_path.write_text(markdown(summary))
    print(f"status={summary['status']}")
    print(f"summary_json={json_path}")
    print(f"report_markdown={markdown_path}")
    if summary["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
