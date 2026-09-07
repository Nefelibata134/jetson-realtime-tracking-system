#!/usr/bin/env python3
"""Calibration-only GT-height diagnostics; official TrackEval results remain authoritative."""
from __future__ import annotations

import argparse
import csv
import importlib
import json
import math
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from export_yolox_tiny_onnx import sha256

SEQUENCES = {"MOT17-02-FRCNN": 600, "MOT17-04-FRCNN": 1050,
             "MOT17-05-FRCNN": 837, "MOT17-10-FRCNN": 654}
TRACKEVAL_COMMIT = "12c8791b303e0a0b50f753af204249e622d0281a"
BINS = ("lt50", "50_to_lt100", "100_to_lt200", "ge200")


def height_bin(height):
    if not math.isfinite(height) or height <= 0:
        raise ValueError("GT box height must be positive and finite")
    return BINS[sum(height >= boundary for boundary in (50, 100, 200))]


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def freeze(data_root):
    sequences = {}
    for sequence, length in SEQUENCES.items():
        gt = data_root / sequence / "gt/gt.txt"
        counts = dict.fromkeys(BINS, 0)
        identities, observations = set(), set()
        with gt.open(encoding="utf-8") as stream:
            for row in csv.reader(stream):
                frame, identity = int(row[0]), int(row[1])
                if not 1 <= frame <= length:
                    raise ValueError("GT frame outside calibration sequence")
                if int(row[6]) != 0 and int(row[7]) == 1:
                    key = frame, identity
                    if key in observations:
                        raise ValueError("Duplicate valid GT observation")
                    observations.add(key)
                    identities.add(identity)
                    counts[height_bin(float(row[5]))] += 1
        sequences[sequence] = {"frames": length, "gt_sha256": sha256(gt),
                               "seqinfo_sha256": sha256(data_root / sequence / "seqinfo.ini"),
                               "valid_gt_observations": len(observations), "valid_gt_ids": len(identities),
                               "height_observations": counts}
    return {"schema_version": 1, "sequences": sequences, "pixel_basis": "original_image_gt_height_no_resize",
            "valid_gt": "TrackEval MOT17 DO_PREPROC: mark != 0 and class == 1; no extra visibility filter",
            "bins": list(BINS), "trackeval_commit": TRACKEVAL_COMMIT,
            "thresholds": {"score": .10, "nms": .45, "track": .30, "new_track": .40, "match": .80, "buffer": 30},
            "matching": "fixed TrackEval CLEAR IoU 0.5 after official preprocessing; bin after full-frame matching",
            "interruption": "matched-missed-rematched within consecutive eligible GT frames; bin at first missed frame; initial/final misses excluded",
            "quality_gate": "detection recall for h<100 increases; detection FN and track interruptions for h<100 decrease; aggregate HOTA/IDF1/MOTA do not decrease",
            "csi_gate": {"input": [1280, 720], "effective_fps_min": 30, "dropped_frames_max": 0,
                         "sequence_gaps_max": 0, "e2e_p95_ms_max": 33.33},
            "power": "25W unchanged clock controls", "holdout_allowed": False}


def interruption_bins(observations):
    """Observations are (zero-based frame, GT id, height, matched) after official matching."""
    counts = dict.fromkeys(BINS, 0)
    state = {}
    for frame, identity, height, matched in observations:
        previous_frame, seen_match, missing_bin = state.get(identity, (-2, False, None))
        if previous_frame != frame - 1:
            seen_match, missing_bin = False, None
        if matched:
            if seen_match and missing_bin is not None:
                counts[missing_bin] += 1
            seen_match, missing_bin = True, None
        elif seen_match and missing_bin is None:
            missing_bin = height_bin(height)
        state[identity] = frame, seen_match, missing_bin
    return counts


def grouped_matches(data):
    import numpy as np
    clear_module = importlib.import_module("trackeval.metrics.clear")
    original = clear_module.linear_sum_assignment
    active = iter(t for t in range(data["num_timesteps"]) if len(data["gt_ids"][t]) and len(data["tracker_ids"][t]))
    matched_rows = {}
    def record(cost):
        t = next(active)
        rows, cols = original(cost)
        accepted = -cost[rows, cols] > np.finfo(float).eps
        matched_rows[t] = set(int(row) for row in rows[accepted])
        return rows, cols
    with patch.object(clear_module, "linear_sum_assignment", record):
        official = clear_module.CLEAR({"PRINT_CONFIG": False}).eval_sequence(data)
    groups = {key: {"gt": 0, "tp": 0, "fn": 0} for key in BINS}
    observations = []
    for t, (ids, boxes) in enumerate(zip(data["gt_ids"], data["gt_dets"])):
        for index, (identity, box) in enumerate(zip(ids, boxes)):
            matched = index in matched_rows.get(t, set())
            group = groups[height_bin(float(box[3]))]
            group["gt"] += 1
            group["tp" if matched else "fn"] += 1
            observations.append((t, int(identity), float(box[3]), matched))
    if sum(g["tp"] for g in groups.values()) != int(official["CLR_TP"]):
        raise ValueError("Diagnostic TP does not reconcile with official CLEAR")
    interruptions = interruption_bins(observations)
    for name, group in groups.items():
        group["recall"] = group["tp"] / group["gt"] if group["gt"] else None
        group["interruptions"] = interruptions[name]
    return {"groups": groups, "official_clear_reconciliation": {
        key: int(official[key]) for key in ("CLR_TP", "CLR_FP", "CLR_FN", "IDSW", "Frag")}}


def detections_to_mot(source, target, frames):
    identity, count = 0, 0
    with source.open(encoding="utf-8") as stream, target.open("x", encoding="utf-8") as out:
        for count, line in enumerate(stream, 1):
            record = json.loads(line)
            if record["frame"] != count or count > frames:
                raise ValueError("Missing, duplicate or extra diagnostic frame")
            for box in record["detections"]:
                if len(box) != 5 or not all(math.isfinite(v) for v in box) or min(box[2:4]) <= 0:
                    raise ValueError("Invalid detection geometry")
                x, y, width, height, score = box
                if not 0 <= score <= 1:
                    raise ValueError("Invalid confidence")
                identity += 1
                # Match MotChallengeWriter: zero-based image coordinates -> MOT +1.
                out.write(f"{count},{identity},{x+1:.6f},{y+1:.6f},{width:.6f},{height:.6f},{score:.6f},-1,-1,-1\n")
    if count != frames:
        raise ValueError("Incomplete diagnostic frame coverage")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, help="Create protocol before inference; never overwrite")
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--trackeval", type=Path)
    parser.add_argument("--tracks-root", type=Path, help="Contains MODEL/data/SEQUENCE.txt")
    parser.add_argument("--detections-root", type=Path, help="Contains MODEL/SEQUENCE.jsonl")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    current = freeze(args.data_root)
    if args.freeze:
        write_new(args.freeze, current)
        print(json.dumps(current, indent=2))
        return 0
    if not all((args.protocol, args.trackeval, args.tracks_root, args.detections_root, args.output_dir)):
        parser.error("Scoring requires protocol, TrackEval, both evidence roots and a new output directory")
    if current != json.loads(args.protocol.read_text(encoding="utf-8")):
        raise ValueError("Frozen GT, protocol or thresholds changed")
    commit = subprocess.check_output(["git", "-C", str(args.trackeval), "rev-parse", "HEAD"], text=True).strip()
    if commit != TRACKEVAL_COMMIT or subprocess.check_output(["git", "-C", str(args.trackeval), "status", "--porcelain"], text=True).strip():
        raise ValueError("TrackEval identity changed")
    sys.path.insert(0, str(args.trackeval.resolve()))
    from trackeval.datasets import MotChallenge2DBox
    args.output_dir.mkdir(parents=True, exist_ok=False)
    results = {"scope": "custom calibration diagnostics, not official stratified TrackEval metrics",
               "protocol_sha256": sha256(args.protocol), "models": {}}
    for model in ("tiny416", "tiny640"):
        derived = args.output_dir / "derived-detections" / model / "data"
        derived.mkdir(parents=True, exist_ok=False)
        for sequence, frames in SEQUENCES.items():
            detections_to_mot(args.detections_root / model / f"{sequence}.jsonl", derived / f"{sequence}.txt", frames)
        results["models"][model] = {}
        for label, root in (("tracks", args.tracks_root), ("detections", args.output_dir / "derived-detections")):
            dataset = MotChallenge2DBox({"GT_FOLDER": str(args.data_root), "TRACKERS_FOLDER": str(root),
                "TRACKERS_TO_EVAL": [model], "SEQ_INFO": SEQUENCES, "SKIP_SPLIT_FOL": True,
                "DO_PREPROC": True, "PRINT_CONFIG": False, "BENCHMARK": "MOT17", "SPLIT_TO_EVAL": "train"})
            results["models"][model][label] = {}
            for sequence in SEQUENCES:
                data = dataset.get_preprocessed_seq_data(dataset.get_raw_seq_data(model, sequence), "pedestrian")
                grouped = grouped_matches(data)
                if {key: value["gt"] for key, value in grouped["groups"].items()} != current["sequences"][sequence]["height_observations"]:
                    raise ValueError("Height denominators differ from frozen valid GT")
                if label == "detections":
                    # Per-frame detection ids are artificial; do not publish identity metrics.
                    grouped.pop("official_clear_reconciliation")
                    for group in grouped["groups"].values():
                        group.pop("interruptions")
                results["models"][model][label][sequence] = grouped
    write_new(args.output_dir / "height-diagnostics.json", results)
    print("height_diagnostics=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
