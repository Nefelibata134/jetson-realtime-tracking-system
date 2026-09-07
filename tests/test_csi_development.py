import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("csi_development", ROOT / "scripts/csi_development.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)
CONFIG = ROOT / "configs/benchmarks/tiny_resolution_development_v2.json"


class CsiDevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.config = MOD.load_config(CONFIG)

    def test_explicit_same_recipe(self):
        args = MOD.command(self.config, "binary", "engine", Path("new-run"))
        for flag, expected in (("score-threshold", "0.1"), ("nms-threshold", "0.45"),
                               ("track-threshold", "0.3"), ("new-track-threshold", "0.4"),
                               ("match-threshold", "0.8"), ("frames", "3600"), ("log-interval", "1")):
            self.assertEqual(args[args.index("--" + flag) + 1], expected)
        for flag in ("event-jsonl", "event-snapshot-dir", "event-clip-dir", "output-video", "metrics-json", "event-line"):
            self.assertIn("--" + flag, args)
        self.assertNotIn("sudo", args)

    def test_forbid_silent_threshold_and_holdout_changes(self):
        for key, value in (("holdout_allowed", True), ("default_switch_authorized", True),
                           ("warmup_frames", 30), ("power_mode_id", 1),
                           ("queue_capacity", 3), ("thermal_abort_c", 100),
                           ("events", {**self.config["events"], "roi": [0, 0, 1, 1]}),
                           ("gate", {**self.config["gate"], "effective_fps_min": 29}),
                           ("csi", {**self.config["csi"], "width": 1920}),
                           ("outputs", {**self.config["outputs"], "snapshots": False}),
                           ("thresholds", dict(score=.25, nms=.45, track=.3, new_track=.4, match=.8, buffer=30))):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as root:
                config = copy.deepcopy(self.config)
                config[key] = value
                path = Path(root) / "config.json"
                path.write_text(json.dumps(config))
                with self.assertRaises(ValueError):
                    MOD.load_config(path)

    def fixture(self):
        n = self.config["measured_frames"]
        records = [{"monotonic_ns": int(1e9 + i * 1e9 / 30), "line": f"frame={i+301} e2e_ms=20.0"} for i in range(n)]
        latency = {key: {"samples": n, "p95": 20.} for key in
                   ("end_to_end", "tensorrt_inference", "detector_preprocess", "detector_postprocess", "tracking", "event_io", "event_io_active")}
        device = {key: {"samples": 250, "max": 10} for key in
                  ("ram_used_mb", "cpu_utilization_percent", "gpu_utilization_percent", "input_power_w", "junction_temperature_c")}
        device["available"] = True
        metrics = dict(schema_version=1, source="csi", status=dict(target_reached=True, continuous=False, invalid_frames=0),
                       pipeline=dict(warmup_frames=300, measured_frames=n, target_frames=n, effective_fps=30.,
                                     warmup_dropped_frames=5, dropped_frames=0, dropped_frames_total=5, sequence_gaps=0,
                                     restart_attempts=0, restart_successes=0, tracker_resets=0, queue_capacity=2,
                                     roi_intrusion_events=1, line_crossing_events=1, dwell_events=1),
                       outputs=dict(annotated_video=dict(enabled=True, frames_submitted=n, frames_written=n, frames_dropped=0,
                                                         encoder="x264", bitrate_kbps=10000),
                                    event_journal=dict(enabled=True, records_written=3), snapshots=dict(enabled=True, written=3),
                                    event_clips=dict(enabled=True, started=3, completed=3, skipped=0)), latency_ms=latency, device=device)
        return metrics, records

    def test_numeric_pass_still_requires_scene_and_decode_review(self):
        metrics, records = self.fixture()
        result = MOD.summarize(self.config, metrics, records, 0)
        self.assertEqual(result["numeric_gate"], "PASS")
        self.assertEqual(result["overall"], "REVIEW_REQUIRED")
        self.assertEqual(len(result["observer_windows"]), 6)
        self.assertEqual(result["warmup_dropped_frames"], 5)

    def test_empty_scene_fps_rounding_and_drop_cannot_pass(self):
        for field, value in (("line_crossing_events", 0), ("effective_fps", 29.9999),
                             ("effective_fps", float("nan")), ("dropped_frames", 1), ("sequence_gaps", 1)):
            with self.subTest(field=field):
                metrics, records = self.fixture()
                metrics["pipeline"][field] = value
                self.assertEqual(MOD.summarize(self.config, metrics, records, 0)["overall"], "FAIL")

    def test_missing_or_duplicate_frame_and_child_exit(self):
        metrics, records = self.fixture()
        self.assertEqual(MOD.summarize(self.config, metrics, records[:-1], 0)["overall"], "FAIL")
        self.assertEqual(MOD.summarize(self.config, metrics, records, 1)["overall"], "FAIL")
        with self.assertRaises(ValueError):
            MOD.frame_records([records[0], records[0]])


if __name__ == "__main__":
    unittest.main()
