from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "run_mot17_inference.sh"
THRESHOLDS = [
    "--score-threshold", "0.15", "--nms-threshold", "0.5",
    "--track-threshold", "0.35", "--new-track-threshold", "0.45",
    "--match-threshold", "0.75",
]


@unittest.skipIf(os.name == "nt" or shutil.which("bash") is None,
                 "requires POSIX Bash; executed by Linux host tests and CI")
class Mot17RunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="mot runner ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.train = self.root / "train"
        sequence = self.train / "MOT17-02-FRCNN"
        (sequence / "img1").mkdir(parents=True)
        (sequence / "gt").mkdir()
        (sequence / "seqinfo.ini").write_text(
            "[Sequence]\nname=MOT17-02-FRCNN\nseqLength=1\nimDir=img1\nimExt=.jpg\n"
        )
        (sequence / "img1" / "000001.jpg").write_bytes(b"fixture")
        (sequence / "gt" / "gt.txt").write_text("1,1,0,0,10,10,1,1,1\n")
        self.seqmap = self.root / "seqmap.txt"
        self.seqmap.write_text("name\nMOT17-02-FRCNN\n")
        self.engine = self.root / "fixture.plan"
        self.engine.write_bytes(b"fixture, never deserialized")
        self.binary = self.root / "fake inference"
        self.binary.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\nfrom pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "output = Path(args[args.index('--output') + 1])\n"
            "output.write_text(json.dumps(args))\n"
            "print('fixture_inference=PASS')\n"
        )
        self.binary.chmod(0o755)
        self.output = self.root / "new outputs"
        self.report = self.root / "new reports"

    def run_wrapper(self, *options: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), "--engine", str(self.engine),
             "--data-root", str(self.train), "--seqmap", str(self.seqmap),
             "--binary", str(self.binary), "--output-root", str(self.output),
             "--report-root", str(self.report), *options],
            cwd=ROOT, capture_output=True, text=True, timeout=20,
        )

    def read_command(self) -> list[str]:
        return json.loads((self.output / "MOT17-02-FRCNN.txt").read_text())

    def test_legacy_detector_and_numeric_defaults_are_unchanged(self) -> None:
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        command = self.read_command()
        self.assertNotIn("--detector", command)
        for option, expected in {
            "--score-threshold": "0.10", "--nms-threshold": "0.45",
            "--track-threshold": "0.50", "--new-track-threshold": "0.60",
            "--match-threshold": "0.80", "--track-buffer": "30",
        }.items():
            self.assertEqual(command[command.index(option) + 1], expected)
        self.output = self.root / "zero threshold outputs"
        self.report = self.root / "zero threshold reports"
        zero = self.run_wrapper(
            "--score-threshold", "0", "--nms-threshold", "0", "--match-threshold", "0"
        )
        self.assertEqual(zero.returncode, 0, zero.stdout + zero.stderr)

    def test_candidate_selection_parameters_and_provenance_are_recorded(self) -> None:
        result = self.run_wrapper("--detector", "yolo26", *THRESHOLDS)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        command = self.read_command()
        self.assertEqual(command[:2], ["--detector", "yolo26"])
        for index in range(0, len(THRESHOLDS), 2):
            self.assertEqual(command[command.index(THRESHOLDS[index]) + 1], THRESHOLDS[index + 1])
        contract = (self.report / "run-contract.txt").read_text()
        self.assertIn("candidate_calibration_only=true", contract)
        self.assertIn("source_commit=", contract)
        self.assertIn(str(self.engine), contract)
        self.assertTrue((self.report / "MOT17-02-FRCNN.command.sh").is_file())

    def test_each_missing_candidate_threshold_is_rejected(self) -> None:
        for index in range(0, len(THRESHOLDS), 2):
            with self.subTest(option=THRESHOLDS[index]):
                partial = THRESHOLDS[:index] + THRESHOLDS[index + 2:]
                result = self.run_wrapper("--detector", "yolo26", *partial)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("explicit", result.stderr)
                self.assertFalse(self.output.exists())

    def test_candidate_cannot_read_holdout_sequences(self) -> None:
        self.seqmap.write_text("name\nMOT17-09-FRCNN\n")
        result = self.run_wrapper("--detector", "yolo26", *THRESHOLDS)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("restricted to calibration", result.stdout)
        self.assertFalse(self.output.exists())

    def test_existing_result_paths_are_preserved(self) -> None:
        for destination in (self.output, self.report):
            with self.subTest(destination=destination):
                destination.mkdir()
                sentinel = destination / "retained.txt"
                sentinel.write_text("historical result")
                result = self.run_wrapper()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(sentinel.read_text(), "historical result")
                sentinel.unlink()
                destination.rmdir()

    def test_invalid_parameters_do_not_create_results(self) -> None:
        for options in (
            ("--detector", "unknown"), ("--score-threshold", "nan"),
            ("--nms-threshold", "inf"), ("--score-threshold", "0.8"),
            ("--new-track-threshold", "0.2"), ("--track-buffer", "0"),
        ):
            with self.subTest(options=options):
                result = self.run_wrapper(*options)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.output.exists())

    def test_missing_argument_value_is_rejected(self) -> None:
        result = self.run_wrapper("--score-threshold")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing value", result.stderr)

    def test_runtime_failure_retains_logs_and_prevents_rerun(self) -> None:
        self.binary.write_text("#!/bin/sh\necho fixture_failure\nexit 7\n")
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 7)
        self.assertIn("fixture_failure", (self.report / "MOT17-02-FRCNN.txt").read_text())
        rerun = self.run_wrapper()
        self.assertNotEqual(rerun.returncode, 0)
        self.assertIn("Refusing to overwrite", rerun.stderr)


if __name__ == "__main__":
    unittest.main()
