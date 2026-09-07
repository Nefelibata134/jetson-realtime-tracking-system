import sys
import json
import hashlib
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze_mot17_continuity import trajectory
from compare_mot17_continuity import MODELS, SEQUENCES, four_way_summary, load_manifest, paired_summary, validate_records


def record(matches, identity=1, heights=None):
    heights = heights or [70] * len(matches[0])
    models = {}
    for model, flags in zip(MODELS, matches):
        observations = [(t, h, 1 if matched else None) for t, (h, matched) in enumerate(zip(heights, flags))]
        result = trajectory(observations, 10)
        result["matched_frames"] = [r[0] for r in observations if r[2] is not None]
        result["small_matched_frames"] = [r[0] for r in observations if r[2] is not None and r[1] < 100]
        models[model] = result
    return {"sequence": "MOT17-02-FRCNN", "original_gt_id": identity, "models": models}


class FourCandidateContinuityTests(unittest.TestCase):
    def test_shared_new_and_lost_frames_reconcile(self):
        data = [record([[1, 1, 0], [0, 1, 1], [1, 1, 1], [0, 0, 0]])]
        validate_records(data)
        a, b = paired_summary(data, "tiny416", "tiny640", "small_observations", "both")
        self.assertEqual((a["shared_matched_observations"], a["candidate_gained_observations"], a["candidate_lost_observations"]), (1, 1, 1))
        self.assertEqual(a["gt_observations"], b["gt_observations"])
        self.assertEqual(b["coverage_gt_unchanged"], 1)

    def test_pair_direction_swaps_gain_loss(self):
        data = [record([[1, 0, 0], [1, 1, 1], [0, 0, 0], [0, 0, 0]])]
        a = paired_summary(data, "tiny416", "tiny640", "all_gt")[0]
        b = paired_summary(data, "tiny640", "tiny416", "all_gt")[0]
        self.assertEqual(a["candidate_gained_observations"], b["candidate_lost_observations"])
        self.assertEqual(a["coverage_gt_increased"], b["coverage_gt_decreased"])

    def test_lost_gt_not_disguised_as_reduced_interruptions(self):
        data = [record([[1, 0, 1], [0, 0, 0], [1, 1, 1], [1, 1, 1]])]
        a, b = paired_summary(data, "tiny416", "tiny640", "small_observations", "tiny416_only")
        self.assertEqual(b["cohort"], "reference_only")
        self.assertEqual((a["closed_gap_seconds_count"], b["closed_gap_seconds_count"]), (1, 0))
        self.assertEqual(b["candidate_lost_observations"], 2)
        self.assertEqual(b["censored_gap_seconds_total"], .3)

    def test_four_way_common_population_and_all_masks(self):
        data = [record([[1], [1], [1], [0]], 1), record([[1], [1], [1], [1]], 2)]
        rows, masks = four_way_summary(data, "small_observations")
        self.assertEqual((masks["1110"], masks["1111"], sum(masks.values())), (1, 1, 2))
        self.assertEqual([r["gt_tracks"] for r in rows if r["cohort"] == "all_four_covered"], [1]*4)

    def test_small_cohort_keeps_full_gt_duration(self):
        data = [record([[1, 1, 1]]*4, heights=[70, 120, 70])]
        result = paired_summary(data, "tiny416", "tiny640", "small_observations")[0]
        self.assertEqual(result["gt_observations"], 2)
        self.assertEqual(result["matched_run_seconds_max"], .3)

    def test_empty_cohort_is_unavailable_not_perfect(self):
        data = [record([[0]]*4)]
        a, b = paired_summary(data, "tiny416", "tiny640", "all_gt", "both")
        self.assertIsNone(a["micro_coverage"])
        self.assertIsNone(b["matched_run_seconds_p95"])

    def test_reject_changed_population_and_unbounded_models(self):
        data = [record([[1]]*4)]
        with self.assertRaises(ValueError):
            validate_records(data * 2)
        data[0]["models"]["tiny640"]["small_gt"] = 2
        with self.assertRaises(ValueError):
            validate_records(data)
        with self.assertRaises(ValueError):
            paired_summary([], "other", "tiny640", "all_gt")
        with self.assertRaises(ValueError):
            four_way_summary([], "holdout")

    def test_frozen_development_plan_has_exactly_four_configs(self):
        root = Path(__file__).resolve().parents[1]
        plan = json.loads((root / "configs/benchmarks/tiny_resolution_caviar_v4.json").read_text(encoding="utf-8"))
        self.assertEqual([r["id"] for r in plan["models"]], list(MODELS))
        self.assertEqual([(r["track"], r["new_track"], r["match"]) for r in plan["models"]],
                         [(.30, .40, .80), (.30, .40, .80), (.35, .35, .80), (.30, .45, .75)])
        for r in plan["models"]:
            self.assertEqual((r["score"], r["nms"], r["buffer"]), (.10, .45, 30))
        self.assertEqual([r["id"] for r in plan["caviar"]["sequences"]],
                         ["Walk1", "Browse1", "EnterExitCrossingPaths1front"])
        self.assertEqual([r["frames"] for r in plan["caviar"]["sequences"]], [611, 1043, 383])
        self.assertEqual([r["expected_events"] for r in plan["caviar"]["sequences"]], [5, 2, 2])
        self.assertEqual(plan["replay_gate"]["expected_files"], 16)
        self.assertEqual(plan["caviar"]["max_inference_runs"], 12)
        self.assertFalse(plan["device"]["power_or_clock_switch"])
        self.assertFalse(plan["caviar"]["scoring"]["automatic_winner"])

    def test_manifest_rejects_changed_hash_and_extra_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = {}
            for model in MODELS:
                folder = root / model / "data"
                folder.mkdir(parents=True)
                files = {}
                for sequence in SEQUENCES:
                    file = folder / (sequence + ".txt")
                    file.write_bytes(b"")
                    files[sequence] = {"path": str(file), "sha256": hashlib.sha256(b"").hexdigest()}
                models[model] = {"tracker_id": model, "files": files, "official_CLEAR": dict.fromkeys(SEQUENCES, {})}
            manifest = root / "inputs.json"
            manifest.write_text(json.dumps({"models": models}), encoding="utf-8")
            self.assertEqual(set(load_manifest(manifest)["models"]), set(MODELS))
            file.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                load_manifest(manifest)
            file.write_bytes(b"")
            models[MODELS[0]]["files"]["MOT17-09-FRCNN"] = {}
            manifest.write_text(json.dumps({"models": models}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
