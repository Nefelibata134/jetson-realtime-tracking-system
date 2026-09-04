#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_yolo26_onnx import (  # noqa: E402
    EXPECTED_INPUT_SHAPE,
    EXPECTED_OUTPUT_SHAPE,
    EXPECTED_ULTRALYTICS_VERSION,
    canonicalize_metadata as _canonicalize_metadata,
    main,
    parse_args as _parse_args,
    sha256,
    tensor_shape,
)


# Kept as a compatibility constant for callers of the original YOLO26s module.
EXPECTED_WEIGHT_SHA256 = (
    "646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b"
)


def canonicalize_metadata(model: object) -> None:
    """Preserve the original YOLO26s helper signature."""
    _canonicalize_metadata(model, "yolo26s")


def parse_args():
    """Preserve the original YOLO26s argument parser entry point."""
    return _parse_args(default_model="yolo26s")


if __name__ == "__main__":
    raise SystemExit(
        main([*sys.argv[1:], "--model", "yolo26s"], default_model="yolo26s")
    )
