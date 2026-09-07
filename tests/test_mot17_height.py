import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("mot_height", ROOT / "scripts/diagnose_mot17_height.py")
HEIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HEIGHT)
sys.path.pop(0)


class HeightDiagnosticTest(unittest.TestCase):
    def test_pixel_boundaries_and_invalid_heights(self):
        for height, expected in ((49.99, "lt50"), (50, "50_to_lt100"), (99.99, "50_to_lt100"),
                                 (100, "100_to_lt200"), (200, "ge200")):
            self.assertEqual(HEIGHT.height_bin(height), expected)
        for height in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                HEIGHT.height_bin(height)

    def test_break_requires_reacquisition_and_contiguous_eligible_gt(self):
        rows = [(0, 1, 30, False), (1, 1, 30, True), (2, 1, 60, False),
                (3, 1, 150, False), (4, 1, 210, True), (5, 1, 30, False)]
        self.assertEqual(HEIGHT.interruption_bins(rows),
                         {"lt50": 0, "50_to_lt100": 1, "100_to_lt200": 0, "ge200": 0})
        rows.append((7, 1, 30, True))
        self.assertEqual(sum(HEIGHT.interruption_bins(rows).values()), 1)

    def test_group_changes_alone_do_not_count_as_breaks(self):
        self.assertEqual(sum(HEIGHT.interruption_bins([(i, 1, h, True) for i, h in enumerate((30, 60, 150, 210))]).values()), 0)

    def test_detection_coordinates_and_complete_empty_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "in.jsonl", Path(directory) / "out.txt"
            source.write_text('{"frame":1,"detections":[[0,1,10,20,0.8]]}\n{"frame":2,"detections":[]}\n')
            HEIGHT.detections_to_mot(source, target, 2)
            self.assertEqual(target.read_text(), "1,1,1.000000,2.000000,10.000000,20.000000,0.800000,-1,-1,-1\n")
            with self.assertRaises(FileExistsError):
                HEIGHT.detections_to_mot(source, target, 2)

    def test_incomplete_duplicate_and_invalid_detection_evidence(self):
        for content in ('{"frame":1,"detections":[]}\n',
                        '{"frame":2,"detections":[]}\n',
                        '{"frame":1,"detections":[[0,0,-1,3,0.5]]}\n'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "in.jsonl"
                source.write_text(content)
                with self.assertRaises(ValueError):
                    HEIGHT.detections_to_mot(source, Path(directory) / "out.txt", 2)

    def test_freeze_valid_gt_filters_and_duplicate_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for sequence in HEIGHT.SEQUENCES:
                gt = root / sequence / "gt"
                gt.mkdir(parents=True)
                (gt / "gt.txt").write_text("1,1,0,0,10,49,1,1,0\n1,2,0,0,10,90,0,1,1\n1,3,0,0,10,210,1,7,1\n")
                (gt.parent / "seqinfo.ini").write_text("fixed fixture")
            frozen = HEIGHT.freeze(root)
            for sequence in frozen["sequences"].values():
                self.assertEqual(sequence["valid_gt_observations"], 1)
                self.assertEqual(sequence["height_observations"]["lt50"], 1)
            self.assertFalse(frozen["holdout_allowed"])
            gt_file = root / next(iter(HEIGHT.SEQUENCES)) / "gt/gt.txt"
            gt_file.write_text(gt_file.read_text() + "1,1,0,0,10,49,1,1,1\n")
            with self.assertRaises(ValueError):
                HEIGHT.freeze(root)


if __name__ == "__main__":
    unittest.main()
