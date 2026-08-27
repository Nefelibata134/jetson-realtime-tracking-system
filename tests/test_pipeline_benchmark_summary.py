from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "summarize_pipeline_benchmarks.py"
)
SPEC = importlib.util.spec_from_file_location("pipeline_summary", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PipelineBenchmarkSummaryTest(unittest.TestCase):
    def test_build_row_separates_critical_path_and_background_work(self) -> None:
        runtime_text = """\
benchmark_timestamp=20260821T010203Z
benchmark_profile=full
benchmark_model=nano
benchmark_resolution=720p
power_mode=25W
power_mode_id=1
clocks_locked=true
engine_sha256=abc
runtime_exit_code=0
"""
        metrics = {
            "status": {"target_reached": True, "recovery_exhausted": False},
            "pipeline": {
                "measured_frames": 300,
                "drop_rate_percent": 0.0,
                "effective_fps": 30.0,
                "total_events": 2,
            },
            "latency_ms": {
                "tensorrt_inference": {"samples": 300, "p95": 5.0},
                "event_io_active": {"samples": 2, "p95": 18.0},
                "end_to_end": {"samples": 300, "p95": 15.0},
            },
            "outputs": {
                "snapshots": {"written": 2},
                "event_clips": {
                    "completed": 2,
                    "frames_encoded": 120,
                    "encoding_total_ms": 240.0,
                    "flush_ms": 20.0,
                },
                "annotated_video": {
                    "encoder": "x264",
                    "bitrate_kbps": 10000,
                    "frames_written": 300,
                    "frames_dropped": 0,
                    "encoding_total_ms": 600.0,
                    "flush_ms": 30.0,
                },
            },
            "device": {
                "input_power_w": {"mean": 8.0, "max": 9.0},
                "gpu_utilization_percent": {"max": 80.0},
                "gpu_temperature_c": {"max": 55.0},
                "ram_used_mb": {"max": 2200.0},
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_path = root / "sample.runtime.txt"
            metrics_path = root / "sample.metrics.json"
            runtime_path.write_text(runtime_text)
            metrics_path.write_text(json.dumps(metrics))
            row = MODULE.build_row(runtime_path, metrics_path)

        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["event_io_active_samples"], 2)
        self.assertEqual(row["tensorrt_inference_p95_ms"], 5.0)
        self.assertEqual(row["event_clip_encode_ms_per_frame"], 2.0)
        self.assertEqual(row["video_encode_ms_per_frame"], 2.0)
        self.assertEqual(row["video_encoder"], "x264")
        self.assertEqual(row["video_bitrate_kbps"], 10000)
        self.assertEqual(row["power_mean_w"], 8.0)
        self.assertIn(
            "| PASS | 720p | 25W (1) | x264 | 10000 |",
            MODULE.markdown([row]),
        )

    def test_latest_matrix_keeps_latest_power_resolution_combination(self) -> None:
        rows = [
            {"profile": "full", "model": "nano", "resolution": "720p", "power_mode_id": "1", "video_encoder": "mp4v", "video_bitrate_kbps": 0, "timestamp": "1"},
            {"profile": "full", "model": "nano", "resolution": "720p", "power_mode_id": "1", "video_encoder": "mp4v", "video_bitrate_kbps": 0, "timestamp": "2"},
        ]
        latest = MODULE.latest_matrix(rows)
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["timestamp"], "2")

    def test_latest_matrix_keeps_encoder_profiles_separate(self) -> None:
        common = {
            "profile": "full",
            "model": "nano",
            "resolution": "1080p",
            "power_mode_id": "2",
            "timestamp": "1",
        }
        rows = [
            {**common, "video_encoder": "mp4v", "video_bitrate_kbps": 0},
            {**common, "video_encoder": "x264", "video_bitrate_kbps": 10000},
        ]
        self.assertEqual(len(MODULE.latest_matrix(rows)), 2)

    def test_csv_uses_lf_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.csv"
            MODULE.write_csv(path, [{"status": "PASS"}])
            content = path.read_bytes()

        self.assertNotIn(b"\r", content)
        self.assertEqual(content.count(b"\n"), 2)


if __name__ == "__main__":
    unittest.main()
