#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_MODELS = ("yolo26n", "yolo26s")
DEFAULT_MODEL = "yolo26s"
EXPECTED_ULTRALYTICS_VERSION = "8.4.138"
EXPECTED_INPUT_SHAPE = [1, 3, 640, 640]
EXPECTED_OUTPUT_SHAPE = [1, 84, 8400]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_metadata(model_name: str) -> dict:
    if model_name not in SUPPORTED_MODELS:
        raise SystemExit(f"Unsupported YOLO26 model: {model_name}")
    path = ROOT / "models" / f"{model_name}.json"
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Unable to read model metadata: {path}") from error
    return metadata


def tensor_shape(value_info: object) -> list[int | str]:
    dimensions: Iterable[object] = value_info.type.tensor_type.shape.dim
    shape: list[int | str] = []
    for dimension in dimensions:
        if dimension.HasField("dim_value"):
            shape.append(int(dimension.dim_value))
        elif dimension.HasField("dim_param"):
            shape.append(str(dimension.dim_param))
        else:
            shape.append("?")
    return shape


def tensor_dtype(value_info: object) -> int:
    return int(value_info.type.tensor_type.elem_type)


def canonicalize_metadata(model: object, model_name: str) -> None:
    metadata = {item.key: item.value for item in model.metadata_props}
    metadata.pop("date", None)
    metadata["description"] = (
        f"Ultralytics YOLO26{model_name[-1]} one-to-many detection model"
    )

    del model.metadata_props[:]
    for key in sorted(metadata):
        item = model.metadata_props.add()
        item.key = key
        item.value = metadata[key]


def parse_args(
    argv: list[str] | None = None, *, default_model: str = DEFAULT_MODEL
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a pinned YOLO26 asset to a static one-to-many ONNX graph."
    )
    parser.add_argument(
        "--model",
        choices=SUPPORTED_MODELS,
        default=default_model,
        help="YOLO26 scale to export (default: %(default)s)",
    )
    parser.add_argument("weights", nargs="?", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.weights is None:
        args.weights = Path("models") / f"{args.model}.pt"
    if args.output is None:
        args.output = Path("models") / f"{args.model}.onnx"
    return args


def _require_metadata_contract(metadata: dict, model_name: str) -> None:
    upstream = metadata.get("upstream", {})
    weight = metadata.get("weight", {})
    export = metadata.get("export", {})
    input_contract = metadata.get("input", {})
    output_contract = metadata.get("output", {})
    if (
        upstream.get("project") != "Ultralytics YOLO26"
        or upstream.get("weight_asset_release") != "v8.4.0"
        or upstream.get("source_code_tag") != f"v{EXPECTED_ULTRALYTICS_VERSION}"
        or upstream.get("license") != "AGPL-3.0"
        or metadata.get("name") != f"YOLO26{model_name[-1]}"
        or weight.get("filename") != f"{model_name}.pt"
        or weight.get("tracked") is not False
        or export.get("tool") != "ultralytics"
        or export.get("version") != EXPECTED_ULTRALYTICS_VERSION
        or export.get("format") != "onnx"
        or export.get("opset") != 17
        or export.get("image_size") != 640
        or export.get("batch") != 1
        or export.get("dynamic") is not False
        or export.get("simplify") is not False
        or export.get("end2end") is not False
        or input_contract.get("shape") != EXPECTED_INPUT_SHAPE
        or input_contract.get("dtype") != "float32"
        or output_contract.get("expected_shape") != EXPECTED_OUTPUT_SHAPE
        or output_contract.get("dtype") != "float32"
        or output_contract.get("contains_objectness") is not False
        or output_contract.get("requires_nms") is not True
    ):
        raise SystemExit(f"{model_name} metadata does not match the export contract")


def main(
    argv: list[str] | None = None, *, default_model: str = DEFAULT_MODEL
) -> int:
    args = parse_args(argv, default_model=default_model)
    model_name = args.model
    metadata = load_metadata(model_name)
    _require_metadata_contract(metadata, model_name)
    weights = args.weights.resolve()
    output = args.output.resolve()

    if not weights.is_file():
        raise SystemExit(f"Weight file does not exist: {weights}")
    if output.suffix.lower() != ".onnx":
        raise SystemExit(f"Output must use the .onnx suffix: {output}")

    expected_weight_sha256 = metadata["weight"]["sha256"]
    weight_digest = sha256(weights)
    if weight_digest != expected_weight_sha256:
        raise SystemExit(
            "Weight SHA-256 mismatch: "
            f"expected {expected_weight_sha256}, got {weight_digest}"
        )

    try:
        import onnx
        import torch
        import ultralytics
        from ultralytics import YOLO
    except ImportError as error:
        raise SystemExit(
            "Install requirements/yolo26-export.txt in an isolated environment."
        ) from error

    if ultralytics.__version__ != EXPECTED_ULTRALYTICS_VERSION:
        raise SystemExit(
            "Ultralytics version mismatch: "
            f"expected {EXPECTED_ULTRALYTICS_VERSION}, got {ultralytics.__version__}"
        )

    detector = YOLO(str(weights), task="detect")
    exported = Path(
        detector.export(
            format="onnx",
            imgsz=640,
            batch=1,
            dynamic=False,
            simplify=False,
            opset=17,
            end2end=False,
            device="cpu",
        )
    ).resolve()

    output.parent.mkdir(parents=True, exist_ok=True)
    if exported != output:
        os.replace(exported, output)

    model_onnx = onnx.load(str(output), load_external_data=False)
    canonicalize_metadata(model_onnx, model_name)
    onnx.save(model_onnx, str(output))
    graph = model_onnx.graph
    if len(graph.input) != 1 or len(graph.output) != 1:
        raise SystemExit(
            f"Expected one input and one output, got {len(graph.input)} and "
            f"{len(graph.output)}"
        )

    input_shape = tensor_shape(graph.input[0])
    output_shape = tensor_shape(graph.output[0])
    expected_output = metadata.get("output", {}).get("expected_shape")
    if input_shape != EXPECTED_INPUT_SHAPE or metadata.get("input", {}).get("shape") != input_shape:
        raise SystemExit(
            f"Unexpected input shape: expected {EXPECTED_INPUT_SHAPE}, got {input_shape}"
        )
    if output_shape != EXPECTED_OUTPUT_SHAPE or expected_output != output_shape:
        raise SystemExit(
            f"Unexpected output shape: expected {EXPECTED_OUTPUT_SHAPE}, got {output_shape}"
        )
    if tensor_dtype(graph.input[0]) != onnx.TensorProto.FLOAT or tensor_dtype(graph.output[0]) != onnx.TensorProto.FLOAT:
        raise SystemExit("YOLO26 ONNX input and output must use float32")

    print(f"model={model_name}")
    print(f"ultralytics_version={ultralytics.__version__}")
    print(f"python_version={platform.python_version()}")
    print(f"torch_version={torch.__version__}")
    print(f"onnx_version={onnx.__version__}")
    print(f"weights={weights}")
    print(f"weights_sha256={weight_digest}")
    print("export=end2end_false,static_batch_1,imgsz_640,opset_17,simplify_false")
    print(f"input={graph.input[0].name}:{input_shape}:float32")
    print(f"output={graph.output[0].name}:{output_shape}:float32")
    print(f"onnx={output}")
    print(f"onnx_sha256={sha256(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
