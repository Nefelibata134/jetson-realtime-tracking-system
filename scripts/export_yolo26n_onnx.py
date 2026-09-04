#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_yolo26_onnx import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(
        main([*sys.argv[1:], "--model", "yolo26n"], default_model="yolo26n")
    )
