#!/usr/bin/env python3
"""Compare a reproduced Tiny416 graph with the fixed official graph on calibration images."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from export_yolox_tiny_onnx import (
    CALIBRATION_IMAGES, REFERENCE_SHA256, UPSTREAM_COMMIT, WEIGHT_SHA256,
    sha256, validate_graph,
)


def compare(reference, candidate, atol, rtol):
    import numpy as np
    if reference.shape != candidate.shape:
        return {"pass": False, "shape_mismatch": True}
    if not np.isfinite(reference).all() or not np.isfinite(candidate).all():
        return {"pass": False, "nonfinite": True}
    delta = np.abs(reference.astype(np.float64) - candidate.astype(np.float64))
    allowed = atol + rtol * np.abs(reference.astype(np.float64))
    return {"pass": bool(np.all(delta <= allowed)), "atol": atol, "rtol": rtol,
            "max_abs": float(delta.max()) if delta.size else 0.0,
            "out_of_tolerance": int(np.count_nonzero(delta > allowed)), "elements": int(delta.size)}


def preprocess(image, size):
    import cv2
    import numpy as np
    h, w = image.shape[:2]
    scale = min(size / h, size / w)
    resized = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, np.uint8)
    canvas[:resized.shape[0], :resized.shape[1]] = resized
    return np.ascontiguousarray(canvas.transpose(2, 0, 1)[None], dtype=np.float32), np.float32(scale)


def decode(raw, size, image_shape, scale):
    """Host parity oracle: same YOLOX decode and class-agnostic inclusive-IoU NMS as C++."""
    import numpy as np
    grids, strides = [], []
    for stride in (8, 16, 32):
        yy, xx = np.meshgrid(np.arange(size // stride), np.arange(size // stride), indexing="ij")
        grids.append(np.stack((xx, yy), axis=-1).reshape(-1, 2))
        strides.append(np.full(((size // stride) ** 2, 1), stride, np.float32))
    grid, stride = np.concatenate(grids).astype(np.float32), np.concatenate(strides)
    if raw.shape != (1, len(grid), 85) or not np.isfinite(raw).all():
        raise ValueError("Invalid finite raw YOLOX output")
    values = raw[0]
    labels = values[:, 5:].argmax(axis=1)
    scores = values[:, 4] * values[np.arange(len(values)), labels + 5]
    keep = scores > np.float32(.10)
    coords = (values[keep, :2] + grid[keep]) * stride[keep]
    wh = np.exp(values[keep, 2:4]) * stride[keep]
    boxes = np.concatenate(((coords - wh / 2) / scale, (coords + wh / 2) / scale), axis=1)
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, image_shape[1] - 1)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, image_shape[0] - 1)
    labels, scores = labels[keep], scores[keep]
    valid = np.isfinite(boxes).all(axis=1) & (boxes[:, 2] > boxes[:, 0]) & (boxes[:, 3] > boxes[:, 1])
    boxes, labels, scores = boxes[valid], labels[valid], scores[valid]
    order = np.argsort(-scores, kind="stable")
    retained = []
    areas = (boxes[:, 2:] - boxes[:, :2] + 1).prod(axis=1)
    while len(order):
        idx, rest = order[0], order[1:]
        retained.append(idx)
        intersection = np.maximum(0, np.minimum(boxes[idx, 2:], boxes[rest, 2:])
                                  - np.maximum(boxes[idx, :2], boxes[rest, :2]) + 1).prod(axis=1)
        iou = intersection / (areas[idx] + areas[rest] - intersection)
        order = rest[iou <= np.float32(.45)]
    return np.column_stack((labels[retained], scores[retained], boxes[retained]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True, help="Four calibration first frames named SEQUENCE.jpg")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        raise ValueError("Refusing to overwrite parity evidence")
    candidate = args.export_dir / "yolox_tiny_416.onnx"
    contract = json.loads((args.export_dir / "export.json").read_text(encoding="utf-8"))
    if (sha256(args.reference) != REFERENCE_SHA256 or sha256(candidate) != contract["onnx_sha256"]
            or contract["weight_sha256"] != WEIGHT_SHA256 or contract["upstream_commit"] != UPSTREAM_COMMIT
            or contract["size"] != 416 or contract["status"] != "PASS"):
        raise ValueError("Reference or export identity mismatch")
    for sequence, digest in CALIBRATION_IMAGES.items():
        if sha256(args.images / f"{sequence}.jpg") != digest:
            raise ValueError(f"Calibration frame identity mismatch: {sequence}")
    import cv2
    import numpy as np
    import onnx
    import onnxruntime as ort
    models = [onnx.load(p, load_external_data=False) for p in (args.reference, candidate)]
    for model in models:
        onnx.checker.check_model(model)
        validate_graph(model, 416)
    def conv_parameters(model):
        values = {x.name: onnx.numpy_helper.to_array(x) for x in model.graph.initializer}
        return [[values[x] for x in n.input[1:] if x in values] for n in model.graph.node if n.op_type == "Conv"]
    a, b = map(conv_parameters, models)
    parameter_checks = [[compare(x, y, 1e-6, 1e-5) for x, y in zip(ap, bp)] for ap, bp in zip(a, b)]
    parameters_equal = (len(a) == len(b) == 83 and all(len(ap) == len(bp) == 2 for ap, bp in zip(a, b))
                        and all(c["pass"] for row in parameter_checks for c in row))
    opts = ort.SessionOptions()
    opts.intra_op_num_threads, opts.inter_op_num_threads = 2, 1
    sessions = [ort.InferenceSession(str(p), sess_options=opts, providers=["CPUExecutionProvider"])
                for p in (args.reference, candidate)]
    args.output_dir.mkdir(parents=True, exist_ok=False)
    images = []
    for sequence, digest in CALIBRATION_IMAGES.items():
        image = cv2.imread(str(args.images / f"{sequence}.jpg"))
        tensor, scale = preprocess(image, 416)
        outputs = [session.run(None, {"images": tensor})[0] for session in sessions]
        raw = compare(*outputs, 1e-4, 1e-4)
        dets = [decode(output, 416, image.shape, scale) for output in outputs]
        scores, boxes = compare(dets[0][:, 1], dets[1][:, 1], 1e-4, 1e-4), compare(dets[0][:, 2:], dets[1][:, 2:], .05, 0)
        labels_equal = bool(np.array_equal(dets[0][:, 0], dets[1][:, 0]))
        entry = {"sequence": sequence, "sha256": digest, "image_shape": list(image.shape), "raw": raw,
                 "detection_counts": [len(d) for d in dets], "scores": scores, "boxes": boxes,
                 "labels_equal": labels_equal, "pass": raw["pass"] and scores["pass"] and boxes["pass"] and labels_equal}
        for label, output, detections in zip(("official", "reproduced"), outputs, dets):
            np.save(args.output_dir / f"{sequence}-{label}-raw.npy", output, allow_pickle=False)
            np.save(args.output_dir / f"{sequence}-{label}-detections.npy", detections, allow_pickle=False)
        images.append(entry)
        print(json.dumps(entry), flush=True)
    report = {"status": "PASS" if parameters_equal and all(i["pass"] for i in images) else "FAIL",
              "weight_sha256": WEIGHT_SHA256, "reference_sha256": REFERENCE_SHA256,
              "reproduced_sha256": sha256(candidate), "upstream_commit": UPSTREAM_COMMIT,
              "conv_counts": [len(a), len(b)], "conv_parameters_equal": parameters_equal,
              "parameter_checks": parameter_checks, "images": images,
              "versions": {**contract["versions"], "numpy": np.__version__, "opencv": cv2.__version__, "onnxruntime": ort.__version__},
              "scope": "CPU float32 baseline equivalence; not TensorRT or task-quality evaluation"}
    with (args.output_dir / "parity.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    print(f"baseline_equivalence={report['status']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
