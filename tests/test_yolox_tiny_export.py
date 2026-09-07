import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("tiny_export", ROOT / "scripts/export_yolox_tiny_onnx.py")
EXPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORT)


def graph(size=640):
    def tensor(name, shape):
        dims = [SimpleNamespace(dim_value=v, HasField=lambda name: name == "dim_value") for v in shape]
        return SimpleNamespace(name=name, type=SimpleNamespace(tensor_type=SimpleNamespace(
            elem_type=1, shape=SimpleNamespace(dim=dims))))
    inputs, outputs = EXPORT.expected_shapes(size)
    return SimpleNamespace(graph=SimpleNamespace(input=[tensor("images", inputs)], output=[tensor("output", outputs)],
                           initializer=[], node=[]), opset_import=[SimpleNamespace(domain="", version=11)])


class TinyExportTest(unittest.TestCase):
    def test_metadata_and_baseline_hash_are_separate(self):
        baseline = json.loads((ROOT / "models/yolox_tiny.json").read_text())
        candidate = json.loads((ROOT / "models/yolox_tiny_640.json").read_text())
        self.assertEqual(baseline["sha256"], EXPORT.REFERENCE_SHA256)
        self.assertEqual(candidate["weight"]["sha256"], EXPORT.WEIGHT_SHA256)
        self.assertEqual(candidate["upstream"]["commit"], EXPORT.UPSTREAM_COMMIT)
        self.assertEqual(candidate["input"]["shape"], [1, 3, 640, 640])
        self.assertEqual(candidate["output"]["shape"], [1, 8400, 85])
        self.assertFalse(candidate["default"])
        self.assertFalse(candidate["weight"]["tracked"])

    def test_shapes_and_unsupported_sizes(self):
        self.assertEqual(EXPORT.expected_shapes(416)[1], [1, 3549, 85])
        self.assertEqual(EXPORT.expected_shapes(640)[1], [1, 8400, 85])
        with self.assertRaises(ValueError):
            EXPORT.expected_shapes(608)

    def test_static_contract(self):
        EXPORT.validate_graph(graph(), 640)
        with self.assertRaises(ValueError):
            EXPORT.validate_graph(graph(416), 640)
        for mutation in ("dtype", "dynamic", "decoded", "nms", "external", "opset"):
            value = graph()
            if mutation == "dtype":
                value.graph.output[0].type.tensor_type.elem_type = 10
            elif mutation == "dynamic":
                value.graph.input[0].type.tensor_type.shape.dim[0].HasField = lambda _: False
            elif mutation in ("decoded", "nms"):
                value.graph.node.append(SimpleNamespace(op_type="Exp" if mutation == "decoded" else "NonMaxSuppression"))
            elif mutation == "external":
                value.graph.initializer.append(SimpleNamespace(data_location=1))
            else:
                value.opset_import[0].version = 17
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                EXPORT.validate_graph(value, 640)

    def test_640_requires_complete_passing_calibration_identity(self):
        proof = {"status": "PASS", "weight_sha256": EXPORT.WEIGHT_SHA256,
                 "reference_sha256": EXPORT.REFERENCE_SHA256, "upstream_commit": EXPORT.UPSTREAM_COMMIT,
                 "conv_counts": [83, 83], "conv_parameters_equal": True,
                 "images": [{"sequence": s, "sha256": h, "pass": True} for s, h in EXPORT.CALIBRATION_IMAGES.items()]}
        EXPORT.validate_proof(proof)
        for key, invalid in (("status", "FAIL"), ("images", []), ("weight_sha256", "0" * 64),
                             ("conv_counts", [0, 0]), ("conv_parameters_equal", False)):
            wrong = copy.deepcopy(proof)
            wrong[key] = invalid
            with self.subTest(key=key), self.assertRaises(ValueError):
                EXPORT.validate_proof(wrong)

    def test_refuses_existing_output_before_importing_export_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "reuse"):
                EXPORT.main(["--source", directory, "--weights", str(output / "missing.pth"),
                             "--size", "640", "--output-dir", str(output)])

    def test_refuses_unknown_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.pth"
            path.write_bytes(b"not the official weights")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                EXPORT.main(["--source", directory, "--weights", str(path), "--size", "640",
                             "--output-dir", str(Path(directory) / "new")])

    def test_cli_help_without_model_packages(self):
        for script in ("export_yolox_tiny_onnx.py", "verify_yolox_tiny_416.py"):
            result = subprocess.run([sys.executable, "-B", ROOT / "scripts" / script, "--help"], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
