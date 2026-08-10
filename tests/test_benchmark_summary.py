from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "summarize_jetson_benchmarks.py"
)
SPEC = importlib.util.spec_from_file_location("benchmark_summary", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BenchmarkSummaryTest(unittest.TestCase):
    def test_build_row_combines_runtime_and_telemetry(self) -> None:
        runtime_text = """\
benchmark_timestamp=20260810T010203Z
benchmark_model=nano
benchmark_resolution=720p
power_mode=25W
power_mode_id=1
engine_sha256=abc
measured_frames=600
dropped=6
target_reached=true
recovery_exhausted=false
inference_mean_ms=12.5
inference_p95_ms=13.0
end_to_end_mean_ms=13.2
end_to_end_p95_ms=14.0
effective_fps=29.5
runtime_exit_code=0
"""
        telemetry_text = "\n".join(
            f"GR3D_FREQ {usage}% gpu@{temperature}C tj@{temperature + 1}C VDD_IN {power}mW/{power}mW"
            for usage, temperature, power in (
                (10, 50.0, 8000),
                (20, 51.0, 9000),
                (30, 52.0, 10000),
            )
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_path = root / "sample.runtime.txt"
            telemetry_path = root / "sample.tegrastats.txt"
            runtime_path.write_text(runtime_text)
            telemetry_path.write_text(telemetry_text)
            row = MODULE.build_row(runtime_path, telemetry_path, 0, 0)

        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["measured_frames"], 600)
        self.assertAlmostEqual(row["drop_rate_percent"], 100.0 * 6 / 606)
        self.assertAlmostEqual(row["power_mean_w"], 9.0)
        self.assertAlmostEqual(row["fps_per_watt"], 29.5 / 9.0)
        self.assertEqual(row["gpu_temp_max_c"], 52.0)

    def test_latest_matrix_keeps_latest_combination(self) -> None:
        rows = [
            {"model": "nano", "resolution": "720p", "power_mode_id": "1", "timestamp": "1"},
            {"model": "nano", "resolution": "720p", "power_mode_id": "1", "timestamp": "2"},
        ]
        latest = MODULE.latest_matrix(rows)
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["timestamp"], "2")


if __name__ == "__main__":
    unittest.main()
