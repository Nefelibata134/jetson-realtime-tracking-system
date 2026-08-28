import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "summarize_mot17.py"
SPEC = importlib.util.spec_from_file_location("summarize_mot17", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Mot17SummaryTest(unittest.TestCase):
    def test_extracts_required_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "pedestrian_summary.txt"
            summary.write_text(
                "HOTA DetA MOTA IDSW IDF1\n"
                "41.25 38.10 35.75 27 44.50\n"
            )

            metrics = MODULE.parse_summary(summary)

        self.assertEqual(
            metrics,
            {"HOTA": 41.25, "IDF1": 44.50, "MOTA": 35.75, "IDSW": 27},
        )

    def test_rejects_missing_metric(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "pedestrian_summary.txt"
            summary.write_text("HOTA MOTA IDSW\n41.25 35.75 27\n")

            with self.assertRaisesRegex(ValueError, "IDF1"):
                MODULE.parse_summary(summary)

    def test_renders_explicit_title(self):
        markdown = MODULE.render_markdown(
            {"HOTA": 41.25, "IDF1": 44.50, "MOTA": 35.75, "IDSW": 27},
            Path("reports/pedestrian_summary.txt"),
            "MOT17 校准基线",
        )

        self.assertTrue(markdown.startswith("# MOT17 校准基线\n"))
        self.assertIn("指标由固定版本的官方 TrackEval 计算", markdown)


if __name__ == "__main__":
    unittest.main()
