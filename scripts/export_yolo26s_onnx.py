#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import platform
from pathlib import Path
from typing import Iterable


EXPECTED_WEIGHT_SHA256 = (
    "646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b"
)
EXPECTED_ULTRALYTICS_VERSION = "8.4.138"
EXPECTED_INPUT_SHAPE = [1, 3, 640, 640]
EXPECTED_OUTPUT_SHAPE = [1, 84, 8400]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def canonicalize_metadata(model: object) -> None:
    metadata = {item.key: item.value for item in model.metadata_props}
    metadata.pop("date", None)
    metadata["description"] = "Ultralytics YOLO26s one-to-many detection model"

    del model.metadata_props[:]
    for key in sorted(metadata):
        item = model.metadata_props.add()
        item.key = key
        item.value = metadata[key]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the pinned YOLO26s asset to a static one-to-many ONNX graph."
    )
    parser.add_argument(
        "weights",
        nargs="?",
        type=Path,
        default=Path("models/yolo26s.pt"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("models/yolo26s.onnx"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    weights = args.weights.resolve()
    output = args.output.resolve()

    if not weights.is_file():
        raise SystemExit(f"Weight file does not exist: {weights}")
    if output.suffix.lower() != ".onnx":
        raise SystemExit(f"Output must use the .onnx suffix: {output}")

    weight_digest = sha256(weights)
    if weight_digest != EXPECTED_WEIGHT_SHA256:
        raise SystemExit(
            "Weight SHA-256 mismatch: "
            f"expected {EXPECTED_WEIGHT_SHA256}, got {weight_digest}"
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
    canonicalize_metadata(model_onnx)
    onnx.save(model_onnx, str(output))
    graph = model_onnx.graph
    if len(graph.input) != 1 or len(graph.output) != 1:
        raise SystemExit(
            f"Expected one input and one output, got {len(graph.input)} and "
            f"{len(graph.output)}"
        )

    input_shape = tensor_shape(graph.input[0])
    output_shape = tensor_shape(graph.output[0])
    if input_shape != EXPECTED_INPUT_SHAPE:
        raise SystemExit(
            f"Unexpected input shape: expected {EXPECTED_INPUT_SHAPE}, got {input_shape}"
        )
    if output_shape != EXPECTED_OUTPUT_SHAPE:
        raise SystemExit(
            f"Unexpected output shape: expected {EXPECTED_OUTPUT_SHAPE}, got {output_shape}"
        )

    print(f"ultralytics_version={ultralytics.__version__}")
    print(f"python_version={platform.python_version()}")
    print(f"torch_version={torch.__version__}")
    print(f"onnx_version={onnx.__version__}")
    print(f"weights={weights}")
    print(f"weights_sha256={weight_digest}")
    print("export=end2end_false,static_batch_1,imgsz_640,opset_17,simplify_false")
    print(f"input={graph.input[0].name}:{input_shape}")
    print(f"output={graph.output[0].name}:{output_shape}")
    print(f"onnx={output}")
    print(f"onnx_sha256={sha256(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
