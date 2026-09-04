from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_mot17.py"
SPEC = importlib.util.spec_from_file_location("validate_mot17", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Mot17ValidationTest(unittest.TestCase):
    def create_sequence(self, root: Path, name: str, frame_count: int = 2) -> None:
        sequence = root / name
        image_root = sequence / "img1"
        ground_truth_root = sequence / "gt"
        image_root.mkdir(parents=True)
        ground_truth_root.mkdir()
        (sequence / "seqinfo.ini").write_text(
            "[Sequence]\n"
            f"name={name}\n"
            "imDir=img1\n"
            "frameRate=30\n"
            f"seqLength={frame_count}\n"
            "imWidth=1920\n"
            "imHeight=1080\n"
            "imExt=.jpg\n"
        )
        (ground_truth_root / "gt.txt").write_text("1,1,0,0,10,10,1,1,1\n")
        for frame in range(1, frame_count + 1):
            (image_root / f"{frame:06d}.jpg").write_bytes(b"image")

    def test_accepts_complete_training_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "MOT17-02-FRCNN"
            self.create_sequence(root, name)
            sequence_map = root / "sequences.txt"
            sequence_map.write_text(f"name\n{name}\n")

            results = MODULE.validate_dataset(root, sequence_map)

        self.assertEqual(results, {name: 2})

    def test_rejects_sequence_without_ground_truth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "MOT17-02-FRCNN"
            self.create_sequence(root, name)
            (root / name / "gt" / "gt.txt").unlink()
            sequence_map = root / "sequences.txt"
            sequence_map.write_text(f"name\n{name}\n")

            with self.assertRaisesRegex(ValueError, "ground truth"):
                MODULE.validate_dataset(root, sequence_map)

    def test_rejects_test_split_sequence_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.mkdir(exist_ok=True)
            sequence_map = root / "sequences.txt"
            sequence_map.write_text("name\nMOT17-03-DPM\n")

            with self.assertRaisesRegex(ValueError, "unsupported sequence"):
                MODULE.validate_dataset(root, sequence_map)

    def test_rejects_frame_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "MOT17-02-FRCNN"
            self.create_sequence(root, name, frame_count=2)
            (root / name / "img1" / "000002.jpg").unlink()
            sequence_map = root / "sequences.txt"
            sequence_map.write_text(f"name\n{name}\n")

            with self.assertRaisesRegex(ValueError, "frame count mismatch"):
                MODULE.validate_dataset(root, sequence_map)

    def test_repository_partition_covers_public_training_sequences_once(self) -> None:
        root = Path(__file__).parents[1]
        calibration = MODULE.read_sequence_map(
            root / "configs" / "mot17" / "calibration.txt"
        )
        holdout = MODULE.read_sequence_map(
            root / "configs" / "mot17" / "holdout.txt"
        )

        self.assertTrue(set(calibration).isdisjoint(holdout))
        self.assertEqual(
            set(calibration + holdout),
            MODULE.PUBLIC_TRAIN_SEQUENCES,
        )
        self.assertEqual(set(calibration), MODULE.CALIBRATION_SEQUENCES)

    def test_calibration_guard_rejects_holdout_before_reading_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seqmap = root / "seqmap.txt"
            seqmap.write_text("name\nMOT17-09-FRCNN\n")
            with self.assertRaisesRegex(ValueError, "restricted to calibration"):
                MODULE.validate_dataset(root / "absent", seqmap, calibration_only=True)


if __name__ == "__main__":
    unittest.main()
