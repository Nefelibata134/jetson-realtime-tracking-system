from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


SUMMARY = load("service_soak_summary", ROOT / "scripts" / "summarize_service_soak.py")
COLLECT = load("service_soak_collect", ROOT / "scripts" / "collect_service_soak.py")
CRASH = load("service_crash", ROOT / "scripts" / "inject_service_crash.py")
RTSP = load("rtsp_outage", ROOT / "scripts" / "inject_rtsp_outage.py")


class ServiceStabilityTest(unittest.TestCase):
    def test_ownership_helpers_cover_parent_directory_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            file_path = nested / "sample.jsonl"
            file_path.write_text("{}\n")
            with mock.patch.dict(
                os.environ, {"SUDO_UID": "1000", "SUDO_GID": "1001"}
            ), mock.patch.object(COLLECT.os, "chown", create=True) as chown:
                COLLECT.chown_path(root)
                COLLECT.chown_tree(root)

        visited = {Path(call.args[0]) for call in chown.call_args_list}
        self.assertEqual(visited, {root, nested, file_path})

    def test_runtime_log_parser_accepts_complete_frame_record_only(self) -> None:
        record = COLLECT.parse_frame_line(
            "frame=900 detections=2 tracks=1 queue_ms=0.6 infer_ms=3.5 "
            "track_ms=0.1 event_ms=0.0 event_io_ms=0.0 events=0 e2e_ms=9.2"
        )
        self.assertEqual(record["frame"], 900)
        self.assertEqual(record["e2e_ms"], 9.2)
        self.assertIsNone(COLLECT.parse_frame_line("warmup=1/30 frame=0 infer_ms=50"))

    def write_run(self, root: Path, watchdog_stall: bool = False) -> None:
        metadata = {
            "requested_duration_seconds": 60.0,
            "completed": True,
        }
        root.joinpath("metadata.json").write_text(json.dumps(metadata))
        samples = []
        for index, elapsed in enumerate((0.0, 30.0, 60.0)):
            watchdog = 100 + index * 30
            if watchdog_stall and index == 2:
                watchdog = 130
            samples.append(
                {
                    "elapsed_seconds": elapsed,
                    "service": {
                        "active_state": "active",
                        "sub_state": "running",
                        "main_pid": 42,
                        "n_restarts": 1,
                        "watchdog_timestamp_monotonic_us": watchdog,
                        "memory_current_bytes": int((450 + index) * 1024**2),
                    },
                    "disk_free_bytes": 10 * 1024**3,
                    "spool_bytes": index * 1024,
                    "frame_records_since_sample": 1,
                    "latest_frame": {"frame": index * 900, "infer_ms": 3.5, "e2e_ms": 9.0},
                }
            )
        root.joinpath("samples.jsonl").write_text(
            "".join(json.dumps(sample) + "\n" for sample in samples)
        )
        root.joinpath("tegrastats.log").write_text(
            "RAM 1000/7620MB GR3D_FREQ 20% gpu@55C tj@56C VDD_IN 8000mW\n"
        )
        metrics = {
            "status": {
                "shutdown_requested": True,
                "shutdown_signal": 15,
                "invalid_frames": 0,
                "recovery_exhausted": False,
            },
            "pipeline": {
                "effective_fps": 30.0,
                "drop_rate_percent": 0.0,
                "measured_frames": 1800,
            },
            "latency_ms": {
                "tensorrt_inference": {"p95": 3.6},
                "end_to_end": {"p95": 9.5},
            },
        }
        root.joinpath("final_metrics.json").write_text(json.dumps(metrics))

    def test_soak_summary_passes_healthy_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_run(root)
            summary = SUMMARY.build_summary(root)
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["service"]["watchdog_stall_windows"], 0)
        self.assertEqual(summary["final_runtime_metrics"]["effective_fps"], 30.0)

    def test_soak_summary_rejects_watchdog_stall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_run(root, watchdog_stall=True)
            summary = SUMMARY.build_summary(root)
        self.assertEqual(summary["status"], "FAIL")
        self.assertEqual(summary["service"]["watchdog_stall_windows"], 1)

    def test_process_recovery_requires_new_pid_session_and_watchdog(self) -> None:
        before = {
            "active_state": "active",
            "sub_state": "running",
            "main_pid": 10,
            "n_restarts": 2,
            "status_text": "video analytics runtime is ready",
            "watchdog_timestamp_monotonic_us": 100,
            "current_session": "/state/one",
        }
        after = dict(before)
        after.update(
            {
                "main_pid": 11,
                "n_restarts": 3,
                "watchdog_timestamp_monotonic_us": 200,
                "current_session": "/state/two",
            }
        )
        self.assertEqual(CRASH.evaluate_recovery(before, after), [])
        after["watchdog_timestamp_monotonic_us"] = 100
        self.assertIn(
            "new process did not make watchdog frame progress",
            CRASH.evaluate_recovery(before, after),
        )

    def test_process_kill_command_supports_systemd_option_versions(self) -> None:
        legacy = CRASH.build_kill_command(
            "edge-vision.service", "--kill-who=WHO Whom to send signal to"
        )
        current = CRASH.build_kill_command(
            "edge-vision.service", "--kill-whom=WHO Whom to send signal to"
        )
        self.assertIn("--kill-who=main", legacy)
        self.assertIn("--kill-whom=main", current)
        with self.assertRaises(RuntimeError):
            CRASH.build_kill_command("edge-vision.service", "no selector")

    def test_rtsp_recovery_requires_real_frame_generation(self) -> None:
        values = {
            "target_reached": "true",
            "recovery_exhausted": "false",
            "restart_successes": "1",
            "stream_generation": "1",
            "tracker_resets": "1",
        }
        self.assertEqual(RTSP.evaluate_rtsp_recovery(values, 0), [])
        values["restart_successes"] = "0"
        self.assertTrue(RTSP.evaluate_rtsp_recovery(values, 0))


if __name__ == "__main__":
    unittest.main()
