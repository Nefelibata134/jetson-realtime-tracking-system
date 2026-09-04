import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "export_yolo26_onnx", ROOT / "scripts" / "export_yolo26_onnx.py"
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


EXPECTED_WEIGHT_SHA256 = {
    "yolo26n": "9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef",
    "yolo26s": "646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b",
}


def read_metadata(model_name: str) -> dict:
    return json.loads(
        (ROOT / "models" / f"{model_name}.json").read_text(encoding="utf-8")
    )


class Yolo26ExportTest(unittest.TestCase):
    def test_export_assets_and_environment_are_not_publishable(self) -> None:
        for model_name in EXPECTED_WEIGHT_SHA256:
            for suffix in ("pt", "onnx", "onnx.data", "plan"):
                path = f"models/{model_name}.{suffix}"
                with self.subTest(path=path):
                    self.assertTrue(RELEASE.is_forbidden_artifact(path))
        for path in (".venv-yolo26-export/bin/python", ".env", ".env.local"):
            with self.subTest(path=path):
                self.assertTrue(RELEASE.is_forbidden_artifact(path))
        for model_name in EXPECTED_WEIGHT_SHA256:
            self.assertFalse(
                RELEASE.is_forbidden_artifact(f"models/{model_name}.json")
            )
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
        for model_name, expected_hash in EXPECTED_WEIGHT_SHA256.items():
            with self.subTest(model=model_name):
                metadata = read_metadata(model_name)
                self.assertEqual(metadata["name"], f"YOLO26{model_name[-1]}")
                self.assertEqual(metadata["weight"]["sha256"], expected_hash)
                self.assertEqual(
                    metadata["export"]["version"], EXPORT.EXPECTED_ULTRALYTICS_VERSION
                )
                self.assertEqual(metadata["input"]["shape"], EXPORT.EXPECTED_INPUT_SHAPE)
                self.assertEqual(
                    metadata["output"]["expected_shape"], EXPORT.EXPECTED_OUTPUT_SHAPE
                )
                self.assertFalse(metadata["export"]["end2end"])
                self.assertTrue(metadata["output"]["requires_nms"])
                self.assertEqual(metadata["host_export_verification"]["repeat_exports"], 2)
                self.assertTrue(
                    metadata["host_export_verification"]["repeat_hash_equal"]
                )
                self.assertFalse(
                    metadata["host_export_verification"]["jetson_engine_validated"]
                )

    def test_shared_and_scale_specific_entrypoints(self) -> None:
        args = EXPORT.parse_args(
            ["--model", "yolo26n", "weights.pt", "--output", "out.onnx"]
        )
        self.assertEqual(args.model, "yolo26n")
        self.assertEqual(args.weights, Path("weights.pt"))
        self.assertEqual(args.output, Path("out.onnx"))
        for script_name, model_name in (
            ("export_yolo26n_onnx.py", "yolo26n"),
            ("export_yolo26s_onnx.py", "yolo26s"),
        ):
            with self.subTest(script=script_name):
                script = (ROOT / "scripts" / script_name).read_text(encoding="utf-8")
                self.assertIn("export_yolo26_onnx", script)
                self.assertIn(f'"{model_name}"', script)


if __name__ == "__main__":
    unittest.main()
