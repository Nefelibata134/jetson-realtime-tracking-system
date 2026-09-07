import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze_mot17_continuity import aggregate, cohort, trajectory


class ContinuityTests(unittest.TestCase):
    def test_closed_gap_and_same_identity_runs(self):
        result = trajectory([(0, 70, 1), (1, 70, 1), (2, 70, None), (3, 70, None), (4, 70, 2), (5, 70, 3)], 2)
        self.assertEqual(result["tp"], 4)
        self.assertEqual(result["interruptions"][0]["seconds"], 1)
        self.assertEqual(result["matched_run_seconds"], [1, 1])
        self.assertEqual(result["same_identity_run_seconds"], [1, .5, .5])
        self.assertEqual(result["small_start_interruptions"], 1)

    def test_initial_terminal_absence_are_not_closed_interruptions(self):
        result = trajectory([(0, 80, None), (1, 80, 1), (2, 80, None), (5, 80, 1), (6, 80, None)], 2)
        self.assertEqual(result["interruptions"], [])
        self.assertEqual(len(result["censored_misses"]), 3)
        self.assertEqual(result["gt_segments"], 2)

    def test_gt_height_transition_does_not_break_tracking(self):
        result = trajectory([(0, 80, 1), (1, 120, 1), (2, 80, 1)], 30)
        self.assertEqual(result["matched_run_seconds"], [.1])
        self.assertEqual(result["small_gt"], 2)
        self.assertEqual(result["small_tp"], 2)

    def test_interruption_bin_uses_first_missed_height(self):
        small_miss = trajectory([(0, 120, 1), (1, 80, None), (2, 120, 1)], 30)
        large_miss = trajectory([(0, 80, 1), (1, 120, None), (2, 80, 1)], 30)
        self.assertEqual(small_miss["small_start_interruptions"], 1)
        self.assertEqual(large_miss["small_start_interruptions"], 0)

    def test_same_gt_denominator_and_uncovered_are_included(self):
        a = trajectory([(i, 70, None) for i in range(10)], 10)
        b = trajectory([(i, 70, 3) for i in range(10)], 10)
        pairs = [{"tiny416": a, "tiny640": b, "lifetime_cohort": cohort(a["tp"], b["tp"]), "small_cohort": "tiny640_only"}]
        self.assertEqual(pairs[0]["lifetime_cohort"], "tiny640_only")
        first = aggregate(pairs, "tiny416", "small_observations")
        second = aggregate(pairs, "tiny640", "small_observations")
        self.assertEqual(first["gt_observations"], second["gt_observations"])
        self.assertEqual(first["micro_coverage"], 0)
        self.assertEqual(second["micro_coverage"], 1)
        self.assertEqual(aggregate(pairs, "tiny416", "all_gt", "both")["micro_coverage"], None)

    def test_neither_cohort_and_duplicate_rejection(self):
        self.assertEqual(cohort(0, 0), "neither")
        with self.assertRaises(ValueError):
            trajectory([(0, 70, 1), (0, 70, 1)], 30)
        with self.assertRaises(ValueError):
            trajectory([(0, 70, 1)], 0)


if __name__ == "__main__":
    unittest.main()
