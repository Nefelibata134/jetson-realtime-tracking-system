from __future__ import annotations

import copy
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import caviar_protocol as protocol  # noqa: E402


EVALUATOR_SPEC = importlib.util.spec_from_file_location(
    "evaluate_caviar_events", ROOT / "scripts" / "evaluate_caviar_events.py"
)
EVALUATOR = importlib.util.module_from_spec(EVALUATOR_SPEC)
assert EVALUATOR_SPEC.loader is not None
EVALUATOR_SPEC.loader.exec_module(EVALUATOR)

PREPARER_SPEC = importlib.util.spec_from_file_location(
    "prepare_caviar_media", ROOT / "scripts" / "prepare_caviar_media.py"
)
PREPARER = importlib.util.module_from_spec(PREPARER_SPEC)
assert PREPARER_SPEC.loader is not None
PREPARER_SPEC.loader.exec_module(PREPARER)

RUNNER_SPEC = importlib.util.spec_from_file_location(
    "run_caviar_external_validation",
    ROOT / "scripts" / "run_caviar_external_validation.py",
)
RUNNER = importlib.util.module_from_spec(RUNNER_SPEC)
assert RUNNER_SPEC.loader is not None
RUNNER_SPEC.loader.exec_module(RUNNER)


class CaviarExternalValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = protocol.load_json(ROOT / "configs" / "caviar" / "dataset.json")
        cls.review = protocol.load_json(
            ROOT / "configs" / "caviar" / "rules.review.json"
        )

    def frozen_rules(self) -> dict:
        config = copy.deepcopy(self.review)
        config.update(
            {
                "status": "frozen",
                "reviewer": "test-reviewer",
                "reviewed_at_utc": "2026-09-01T01:00:00Z",
                "frozen_at_utc": "2026-09-01T01:01:00Z",
            }
        )
        rules = protocol.rules_by_pair(config)
        rules["inria_line"]["line"] = [0.5, 0.0, 0.5, 1.0]
        rules["inria_dwell"]["roi"] = [0.2, 0.2, 0.8, 0.9]
        rules["inria_dwell"]["dwell_seconds"] = 0.08
        rules["lisbon_front_roi"]["roi"] = [0.2, 0.2, 0.8, 0.9]
        return config

    def test_repository_selection_has_required_splits_and_roles(
        self,
    ) -> None:
        protocol.validate_dataset_config(self.dataset)

        pairs: dict[str, set[str]] = {}
        for sequence in self.dataset["sequences"]:
            pairs.setdefault(sequence["pair_id"], set()).add(sequence["split"])

        self.assertEqual(len(self.dataset["sequences"]), 7)
        self.assertEqual(
            {sequence["sequence_id"] for sequence in self.dataset["sequences"]},
            {
                "Walk1",
                "Walk2",
                "Browse1",
                "Browse2",
                "Browse_WhileWaiting2",
                "EnterExitCrossingPaths1front",
                "EnterExitCrossingPaths2front",
            },
        )
        negative_control = protocol.sequence_by_id(self.dataset, "Browse_WhileWaiting2")
        positive_dwell = protocol.sequence_by_id(self.dataset, "Browse2")
        self.assertTrue(protocol.allows_empty_ground_truth(negative_control))
        self.assertFalse(protocol.allows_empty_ground_truth(positive_dwell))
        self.assertEqual(
            self.dataset["selection_policy"]["semantic_audit"]["Browse2"], "pass"
        )
        self.assertEqual(
            self.dataset["selection_policy"]["runtime_semantics"][
                "roi_startup_occupancy"
            ],
            "emit_after_two_confirmed_inside_frames",
        )
        for sequence in self.dataset["sequences"]:
            protocol.require_holdout_semantic_audit(self.dataset, sequence)
            protocol.require_holdout_truth_audit(self.dataset, sequence)
        self.assertTrue(
            all(
                protocol.SHA256_PATTERN.fullmatch(sequence[asset]["sha256"])
                for sequence in self.dataset["sequences"]
                for asset in ("video", "annotation")
            )
        )
        self.assertEqual(
            pairs,
            {
                "inria_line": {"development", "holdout"},
                "inria_dwell": {"development", "holdout"},
                "lisbon_front_roi": {"development", "holdout"},
            },
        )

    def test_pending_review_cannot_generate_frozen_truth(self) -> None:
        protocol.validate_rules_config(self.review, self.dataset, require_frozen=False)
        with self.assertRaisesRegex(ValueError, "not frozen"):
            protocol.validate_rules_config(
                self.review, self.dataset, require_frozen=True
            )

    def test_pending_holdout_semantic_audit_is_rejected(self) -> None:
        dataset = copy.deepcopy(self.dataset)
        dataset["selection_policy"]["semantic_audit"]["Browse2"] = (
            "pending_human_review"
        )
        sequence = protocol.sequence_by_id(dataset, "Browse2")

        with self.assertRaisesRegex(ValueError, "not approved"):
            protocol.require_holdout_semantic_audit(dataset, sequence)

    def test_pending_holdout_truth_audit_is_rejected(self) -> None:
        dataset = copy.deepcopy(self.dataset)
        dataset["selection_policy"]["truth_audit"]["Walk2"] = "pending_human_review"
        sequence = protocol.sequence_by_id(dataset, "Walk2")

        with self.assertRaisesRegex(ValueError, "truth audit is not approved"):
            protocol.require_holdout_truth_audit(dataset, sequence)

    def test_parser_uses_bounding_box_bottom_center(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.xml"
            path.write_text(
                '<?xml version="1.0"?><dataset name="Walk1">'
                '<frame number="0"><objectlist><object id="7">'
                '<box h="40" w="20" xc="96" yc="100"/>'
                "</object></objectlist><grouplist/></frame></dataset>",
                encoding="utf-8",
            )
            name, frames = protocol.read_ground_truth_frames(
                path, frame_width=384, frame_height=288
            )

        self.assertEqual(name, "Walk1")
        self.assertEqual(frames[0].tracks[0].track_id, 7)
        self.assertAlmostEqual(frames[0].tracks[0].anchor_x, 0.25)
        self.assertAlmostEqual(frames[0].tracks[0].anchor_y, 120 / 288)

    def test_media_conversion_rebuilds_the_fixed_frame_timeline(self) -> None:
        command = PREPARER.build_conversion_command(
            Path("source.mpg"),
            Path("destination.mp4"),
            bitrate_kbps=2500,
            frames_per_second=25,
        )

        self.assertIn("videorate", command)
        self.assertIn("video/x-raw,format=I420,framerate=25/1", command)

    def test_external_runner_buffers_the_cold_start_without_frame_loss(self) -> None:
        self.assertEqual(RUNNER.INPUT_QUEUE_CAPACITY, 8)

    def test_roi_truth_requires_two_confirmed_inside_frames(self) -> None:
        sequence = protocol.sequence_by_id(self.dataset, "EnterExitCrossingPaths1front")
        rule = protocol.rules_by_pair(self.frozen_rules())["lisbon_front_roi"]
        frames = [
            protocol.GroundTruthFrame(0, (protocol.GroundTruthTrack(1, 0.1, 0.5),)),
            protocol.GroundTruthFrame(1, (protocol.GroundTruthTrack(1, 0.5, 0.5),)),
            protocol.GroundTruthFrame(2, (protocol.GroundTruthTrack(1, 0.5, 0.5),)),
        ]

        events = protocol.generate_events(sequence, rule, frames, frames_per_second=25)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["frame_sequence"], 2)

    def test_roi_truth_reports_occupant_present_at_startup(self) -> None:
        sequence = protocol.sequence_by_id(self.dataset, "EnterExitCrossingPaths1front")
        rule = protocol.rules_by_pair(self.frozen_rules())["lisbon_front_roi"]
        frames = [
            protocol.GroundTruthFrame(0, (protocol.GroundTruthTrack(1, 0.5, 0.5),)),
            protocol.GroundTruthFrame(1, (protocol.GroundTruthTrack(1, 0.5, 0.5),)),
        ]

        events = protocol.generate_events(sequence, rule, frames, frames_per_second=25)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["frame_sequence"], 1)

    def test_line_truth_preserves_crossing_direction(self) -> None:
        sequence = protocol.sequence_by_id(self.dataset, "Walk1")
        rule = protocol.rules_by_pair(self.frozen_rules())["inria_line"]
        frames = [
            protocol.GroundTruthFrame(0, (protocol.GroundTruthTrack(1, 0.25, 0.5),)),
            protocol.GroundTruthFrame(1, (protocol.GroundTruthTrack(1, 0.75, 0.5),)),
        ]

        events = protocol.generate_events(sequence, rule, frames, frames_per_second=25)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["direction"], "positive_to_negative")

    def test_dwell_truth_uses_timestamps_not_frame_count_only(self) -> None:
        sequence = protocol.sequence_by_id(self.dataset, "Browse1")
        rule = protocol.rules_by_pair(self.frozen_rules())["inria_dwell"]
        frames = [
            protocol.GroundTruthFrame(
                number,
                (protocol.GroundTruthTrack(1, 0.5, 0.5),),
            )
            for number in range(3)
        ]

        events = protocol.generate_events(sequence, rule, frames, frames_per_second=25)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["frame_sequence"], 2)
        self.assertEqual(events[0]["pts_ns"], 80_000_000)

    def test_event_matching_is_one_to_one_and_track_id_independent(self) -> None:
        expected = [
            {
                "event_type": "roi_intrusion",
                "frame_sequence": 100,
                "anchor": {"x": 0.5, "y": 0.8},
            }
        ]
        actual = [
            {
                "event_type": "roi_intrusion",
                "frame_sequence": 102,
                "track_id": 99,
                "anchor": {"x": 0.51, "y": 0.79},
            },
            {
                "event_type": "roi_intrusion",
                "frame_sequence": 103,
                "track_id": 100,
                "anchor": {"x": 0.52, "y": 0.79},
            },
        ]

        matches, false_negatives, false_positives = EVALUATOR.match_events(
            expected,
            actual,
            frame_tolerance=10,
            anchor_tolerance=0.1,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(false_negatives, [])
        self.assertEqual(len(false_positives), 1)

    def test_frozen_rules_generate_runtime_arguments(self) -> None:
        rules = protocol.rules_by_pair(self.frozen_rules())

        self.assertEqual(
            protocol.runtime_rule_arguments(rules["inria_line"]),
            [
                "--event-line",
                "0.5",
                "0.0",
                "0.5",
                "1.0",
                "--event-line-direction",
                "any",
            ],
        )


if __name__ == "__main__":
    unittest.main()
