import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "export_yolo26s_onnx", ROOT / "scripts" / "export_yolo26s_onnx.py"
)
assert SPEC is not None and SPEC.loader is not None
EXPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORT)
RELEASE_SPEC = importlib.util.spec_from_file_location(
    "yolo26_release_validation", ROOT / "scripts" / "validate_release.py"
)
assert RELEASE_SPEC is not None and RELEASE_SPEC.loader is not None
RELEASE = importlib.util.module_from_spec(RELEASE_SPEC)
RELEASE_SPEC.loader.exec_module(RELEASE)


class Yolo26ExportTest(unittest.TestCase):
    def test_export_assets_and_environment_are_not_publishable(self) -> None:
        for path in (
            "models/yolo26s.pt",
            "models/yolo26s.onnx",
            "models/yolo26s.onnx.data",
            "models/yolo26s_fp16.plan",
            ".venv-yolo26-export/bin/python",
            ".env",
            ".env.local",
        ):
            with self.subTest(path=path):
                self.assertTrue(RELEASE.is_forbidden_artifact(path))
        self.assertFalse(RELEASE.is_forbidden_artifact("models/yolo26s.json"))
        self.assertFalse(
            RELEASE.is_forbidden_artifact("requirements/yolo26-export.txt")
        )

    def test_sha256_streams_file_contents(self) -> None:
        payload = b"fixed-yolo26-export-test"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.bin"
            path.write_bytes(payload)
            self.assertEqual(EXPORT.sha256(path), hashlib.sha256(payload).hexdigest())

    def test_metadata_matches_export_contract(self) -> None:
        metadata = json.loads(
            (ROOT / "models" / "yolo26s.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            metadata["weight"]["sha256"], EXPORT.EXPECTED_WEIGHT_SHA256
        )
        self.assertEqual(
            metadata["export"]["version"], EXPORT.EXPECTED_ULTRALYTICS_VERSION
        )
        self.assertEqual(metadata["input"]["shape"], EXPORT.EXPECTED_INPUT_SHAPE)
        self.assertEqual(
            metadata["output"]["expected_shape"], EXPORT.EXPECTED_OUTPUT_SHAPE
        )
        self.assertFalse(metadata["export"]["end2end"])
        self.assertTrue(metadata["output"]["requires_nms"])


if __name__ == "__main__":
    unittest.main()
