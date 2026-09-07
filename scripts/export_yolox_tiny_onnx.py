#!/usr/bin/env python3
"""Export the pinned YOLOX-Tiny checkpoint; never rewrite an existing ONNX shape."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_COMMIT = "e1052df71842031413f6030723c3607b839c80ce"
WEIGHT_SHA256 = "9de513de589ac98bb92d3bca53b5af7b9acfa9b0bacb831f7999d0f7afaee8f0"
REFERENCE_SHA256 = "427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7"
CALIBRATION_IMAGES = {
    "MOT17-02-FRCNN": "41ff65408c5338f4a83035fd12e9f5f7b658ee82feacf4512655677032636597",
    "MOT17-04-FRCNN": "53f3d86aad1aa4912b2919bae344919b54d193e72c1c7169ce8bc4685408053c",
    "MOT17-05-FRCNN": "9f4f112b29e93846501db27d2bcc2c99795715aa6376d5b5662d75f2e2f196d7",
    "MOT17-10-FRCNN": "bc655b86e7dcd9993df950217534f2f6cbf85217faba544dce956b834fb053a0",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_shapes(size: int) -> tuple[list[int], list[int]]:
    if size not in (416, 640):
        raise ValueError("Only the 416 baseline and 640 candidate are supported")
    return [1, 3, size, size], [1, sum((size // s) ** 2 for s in (8, 16, 32)), 85]


def validate_graph(model: object, size: int) -> None:
    inputs, outputs = model.graph.input, model.graph.output
    if len(inputs) != 1 or len(outputs) != 1:
        raise ValueError("Expected exactly one input and one output")
    for tensor, name, shape in zip((*inputs, *outputs), ("images", "output"), expected_shapes(size)):
        dims = tensor.type.tensor_type.shape.dim
        if tensor.name != name or tensor.type.tensor_type.elem_type != 1:
            raise ValueError("Expected named float32 input/output")
        if any(not d.HasField("dim_value") for d in dims) or [d.dim_value for d in dims] != shape:
            raise ValueError(f"Unexpected static shape for {name}")
    if [(o.domain, o.version) for o in model.opset_import] != [("", 11)]:
        raise ValueError("Expected ONNX opset 11")
    if any(t.data_location != 0 for t in model.graph.initializer):
        raise ValueError("External ONNX tensor files are not permitted")
    if any(n.op_type in {"NonMaxSuppression", "Exp"} for n in model.graph.node):
        raise ValueError("Expected raw YOLOX output without grid decode or NMS")


def validate_proof(proof: dict) -> None:
    if (proof.get("status") != "PASS" or proof.get("weight_sha256") != WEIGHT_SHA256
            or proof.get("reference_sha256") != REFERENCE_SHA256
            or proof.get("upstream_commit") != UPSTREAM_COMMIT
            or proof.get("conv_counts") != [83, 83]
            or proof.get("conv_parameters_equal") is not True
            or len(proof.get("images", [])) != 4
            or {i.get("sequence"): i.get("sha256") for i in proof.get("images", [])} != CALIBRATION_IMAGES
            or not all(i.get("pass") is True for i in proof.get("images", []))):
        raise ValueError("A passing fixed-image 416 equivalence report is required")


def check_source(source: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()
    if git("rev-parse", "HEAD") != UPSTREAM_COMMIT:
        raise ValueError("YOLOX source commit mismatch")
    # Only imported/export source matters; unrelated case-colliding Android paths
    # in this upstream tag do not invalidate a Windows checkout.
    paths = ("yolox", "exps", "tools", "LICENSE")
    if git("diff", "HEAD", "--", *paths) or git("ls-files", "--others", "--exclude-standard", "--", *paths):
        raise ValueError("YOLOX export source has local changes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--size", type=int, choices=(416, 640), required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory; existing paths are rejected")
    parser.add_argument("--baseline-proof", type=Path, help="Required before exporting 640")
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        raise ValueError("Refusing to reuse output directory")
    if sha256(args.weights) != WEIGHT_SHA256:
        raise ValueError("Official checkpoint SHA-256 mismatch")
    check_source(args.source)
    if args.size == 640:
        if args.baseline_proof is None:
            raise ValueError("Export and verify 416 before exporting 640")
        validate_proof(json.loads(args.baseline_proof.read_text(encoding="utf-8")))
    sys.path.insert(0, str(args.source.resolve()))
    import onnx
    import torch
    from yolox.exp import get_exp
    from yolox.models.network_blocks import SiLU
    from yolox.utils import replace_module

    if torch.__version__.split("+")[0] != "2.11.0" or onnx.__version__ != "1.20.0":
        raise ValueError("Use the pinned requirements/yolox-tiny-export.txt environment")
    torch.set_num_threads(2)
    exp = get_exp(None, "yolox-tiny")
    if (exp.depth, exp.width, exp.num_classes) != (0.33, 0.375, 80):
        raise ValueError("YOLOX-Tiny network configuration mismatch")
    model = exp.get_model().eval()
    checkpoint = torch.load(args.weights.resolve(), map_location="cpu", weights_only=True)
    model.load_state_dict(checkpoint["model"], strict=True)
    model = replace_module(model, torch.nn.SiLU, SiLU)
    model.head.decode_in_inference = False
    args.output_dir.mkdir(parents=True, exist_ok=False)
    output = args.output_dir / f"yolox_tiny_{args.size}.onnx"
    with torch.inference_mode():
        torch.onnx.export(model, torch.zeros(*expected_shapes(args.size)[0]), str(output),
                          input_names=["images"], output_names=["output"], opset_version=11,
                          dynamo=False, external_data=False)
    graph = onnx.load(output, load_external_data=False)
    onnx.checker.check_model(graph)
    validate_graph(graph, args.size)
    report = {
        "status": "PASS", "size": args.size, "weight_sha256": sha256(args.weights),
        "upstream_commit": UPSTREAM_COMMIT, "onnx_sha256": sha256(output),
        "input_shape": expected_shapes(args.size)[0], "output_shape": expected_shapes(args.size)[1],
        "decoded": False, "nms": False, "simplified": False, "opset": 11,
        "versions": {"python": platform.python_version(), "torch": torch.__version__, "onnx": onnx.__version__},
        "baseline_proof_sha256": sha256(args.baseline_proof) if args.baseline_proof else None,
        "command": [sys.executable, *sys.argv], "jetson_engine_validated": False,
    }
    with (args.output_dir / "export.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
