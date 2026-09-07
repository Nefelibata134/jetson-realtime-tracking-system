#!/usr/bin/env python3
"""Paired GT trajectory diagnostics from existing calibration outputs; no inference or tuning."""
from __future__ import annotations

import argparse
import configparser
import csv
import importlib
import json
import math
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from diagnose_mot17_height import SEQUENCES, TRACKEVAL_COMMIT, freeze
from export_yolox_tiny_onnx import sha256

MODELS = ("tiny416", "tiny640")
COHORTS = ("both", "tiny640_only", "tiny416_only", "neither")


def cohort(a, b):
    return "both" if a and b else "tiny416_only" if a else "tiny640_only" if b else "neither"


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "total": 0, "mean": None, "p50": None, "p95": None, "max": None}
    return {"count": len(ordered), "total": sum(ordered), "mean": sum(ordered) / len(ordered),
            "p50": ordered[math.ceil(.50 * len(ordered)) - 1],
            "p95": ordered[math.ceil(.95 * len(ordered)) - 1], "max": ordered[-1]}


def trajectory(observations, fps):
    """(frame, original GT height, matched prediction id or None); one fixed GT identity."""
    if fps <= 0 or not math.isfinite(fps):
        raise ValueError("Invalid sequence frame rate")
    observations = sorted(observations, key=lambda row: row[0])
    if not observations or len({row[0] for row in observations}) != len(observations):
        raise ValueError("Empty or duplicated GT frame")
    if any(not math.isfinite(row[1]) or row[1] <= 0 for row in observations):
        raise ValueError("Invalid GT height")
    segments = [[]]
    for row in observations:
        if segments[-1] and row[0] != segments[-1][-1][0] + 1:
            segments.append([])
        segments[-1].append(row)
    matched_runs, identity_runs, interruptions, censored = [], [], [], []
    adjacent_identity_changes = 0
    for segment in segments:
        start = 0
        while start < len(segment):
            matched = segment[start][2] is not None
            end = start + 1
            while end < len(segment) and (segment[end][2] is not None) == matched:
                end += 1
            if matched:
                matched_runs.append(end - start)
                id_start = start
                for index in range(start + 1, end):
                    if segment[index][2] != segment[index - 1][2]:
                        adjacent_identity_changes += 1
                        identity_runs.append(index - id_start)
                        id_start = index
                identity_runs.append(end - id_start)
            else:
                record = {"first_frame": segment[start][0], "frames": end - start,
                          "seconds": (end - start) / fps, "first_height": segment[start][1],
                          "left_censored": start == 0, "right_censored": end == len(segment)}
                (censored if start == 0 or end == len(segment) else interruptions).append(record)
            start = end
    gt = len(observations)
    tp = sum(row[2] is not None for row in observations)
    small = [row for row in observations if row[1] < 100]
    small_tp = sum(row[2] is not None for row in small)
    if sum(matched_runs) != tp or sum(identity_runs) != tp:
        raise ValueError("Matched duration accounting mismatch")
    if sum(row["frames"] for row in interruptions + censored) != gt - tp:
        raise ValueError("Missing duration accounting mismatch")
    return {"gt": gt, "tp": tp, "fn": gt - tp, "coverage": tp / gt,
            "small_gt": len(small), "small_tp": small_tp, "small_fn": len(small) - small_tp,
            "small_coverage": small_tp / len(small) if small else None,
            "gt_segments": len(segments), "gt_seconds": gt / fps,
            "matched_run_seconds": [n / fps for n in matched_runs],
            "same_identity_run_seconds": [n / fps for n in identity_runs],
            "longest_matched_seconds": max(matched_runs, default=0) / fps,
            "longest_same_identity_seconds": max(identity_runs, default=0) / fps,
            "interruptions": interruptions, "censored_misses": censored,
            "small_start_interruptions": sum(row["first_height"] < 100 for row in interruptions),
            "adjacent_identity_changes_diagnostic_not_official_IDSW": adjacent_identity_changes}


def match_existing(data):
    import numpy as np
    clear = importlib.import_module("trackeval.metrics.clear")
    original = clear.linear_sum_assignment
    active = iter(t for t in range(data["num_timesteps"]) if len(data["gt_ids"][t]) and len(data["tracker_ids"][t]))
    matches = {}

    def record(cost):
        t = next(active)
        rows, cols = original(cost)
        accepted = -cost[rows, cols] > np.finfo(float).eps
        matches[t] = {int(row): int(data["tracker_ids"][t][col]) for row, col in zip(rows[accepted], cols[accepted])}
        return rows, cols

    with patch.object(clear, "linear_sum_assignment", record):
        official = clear.CLEAR({"PRINT_CONFIG": False}).eval_sequence(data)
    if sum(map(len, matches.values())) != int(official["CLR_TP"]):
        raise ValueError("Recorded matches do not reconcile with official CLEAR")
    return matches, {key: int(official[key]) for key in ("CLR_TP", "CLR_FP", "CLR_FN", "IDSW", "Frag")}


def aggregate(pairs, model, scope, selected_cohort="all"):
    eligible = [pair for pair in pairs if scope == "all_gt" or pair[model]["small_gt"] > 0]
    key = "small_cohort" if scope == "small_observations" else "lifetime_cohort"
    selected = [pair for pair in eligible if selected_cohort == "all" or pair[key] == selected_cohort]
    records = [pair[model] for pair in selected]
    gt_key, tp_key = ("small_gt", "small_tp") if scope == "small_observations" else ("gt", "tp")
    gt, tp = sum(r[gt_key] for r in records), sum(r[tp_key] for r in records)
    result = {"scope": scope, "cohort": selected_cohort, "model": model, "gt_tracks": len(records),
              "cohort_basis": key, "duration_scope": "full_eligible_gt_lifetime",
              "gt_observations": gt, "matched_observations": tp, "missed_observations": gt - tp,
              "micro_coverage": tp / gt if gt else None,
              "macro_coverage": sum(r[tp_key] / r[gt_key] for r in records) / len(records) if records else None}
    # Duration statistics stay on the same trajectories' full eligible lifetime. They are not
    # obtained by deleting large-height frames and artificially joining the remaining fragments.
    for field, values in {
        "closed_gap_seconds": [gap["seconds"] for r in records for gap in r["interruptions"]],
        "censored_gap_seconds": [gap["seconds"] for r in records for gap in r["censored_misses"]],
        "matched_run_seconds": [v for r in records for v in r["matched_run_seconds"]],
        "same_identity_run_seconds": [v for r in records for v in r["same_identity_run_seconds"]],
        "longest_matched_seconds_per_gt": [r["longest_matched_seconds"] for r in records],
        "longest_same_identity_seconds_per_gt": [r["longest_same_identity_seconds"] for r in records],
    }.items():
        for stat, value in distribution(values).items():
            result[field + "_" + stat] = value
    result["small_start_interruptions"] = sum(r["small_start_interruptions"] for r in records)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--trackeval", type=Path, required=True)
    parser.add_argument("--tracks-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if freeze(args.data_root) != json.loads(args.protocol.read_text(encoding="utf-8")):
        raise ValueError("Frozen calibration GT/seqinfo/protocol changed")
    commit = subprocess.check_output(["git", "-C", str(args.trackeval), "rev-parse", "HEAD"], text=True).strip()
    if commit != TRACKEVAL_COMMIT or subprocess.check_output(["git", "-C", str(args.trackeval), "status", "--porcelain"], text=True).strip():
        raise ValueError("TrackEval identity changed")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(args.trackeval.resolve()))
    from trackeval.datasets import MotChallenge2DBox
    pairs, official, source_hashes = [], {}, {str(args.protocol): sha256(args.protocol)}
    for sequence in SEQUENCES:
        info = configparser.ConfigParser()
        info.read(args.data_root / sequence / "seqinfo.ini")
        fps = float(info["Sequence"]["frameRate"])
        gt_by_id = {}
        with (args.data_root / sequence / "gt/gt.txt").open() as stream:
            for row in csv.reader(stream):
                if int(row[6]) != 0 and int(row[7]) == 1:
                    gt_by_id.setdefault(int(row[1]), {})[int(row[0]) - 1] = tuple(map(float, row[2:6]))
        original_ids = sorted(gt_by_id)
        sequence_rows = {}
        official[sequence] = {}
        for model in MODELS:
            track_file = args.tracks_root / model / "data" / (sequence + ".txt")
            source_hashes[str(track_file)] = sha256(track_file)
            dataset = MotChallenge2DBox({"GT_FOLDER": str(args.data_root), "TRACKERS_FOLDER": str(args.tracks_root),
                "TRACKERS_TO_EVAL": [model], "SEQ_INFO": SEQUENCES, "SKIP_SPLIT_FOL": True, "DO_PREPROC": True,
                "PRINT_CONFIG": False, "BENCHMARK": "MOT17", "SPLIT_TO_EVAL": "train"})
            data = dataset.get_preprocessed_seq_data(dataset.get_raw_seq_data(model, sequence), "pedestrian")
            matches, official[sequence][model] = match_existing(data)
            observations = {identity: [] for identity in original_ids}
            for t, (ids, boxes) in enumerate(zip(data["gt_ids"], data["gt_dets"])):
                for index, (mapped_id, box) in enumerate(zip(ids, boxes)):
                    original_id = original_ids[int(mapped_id)]
                    if tuple(map(float, box)) != gt_by_id[original_id][t]:
                        raise ValueError("Original GT identity/geometry mapping changed")
                    observations[original_id].append((t, float(box[3]), matches.get(t, {}).get(index)))
            sequence_rows[model] = {identity: trajectory(rows, fps) for identity, rows in observations.items()}
            if sum(r["tp"] for r in sequence_rows[model].values()) != official[sequence][model]["CLR_TP"]:
                raise ValueError("Per-GT total differs from official TP")
        for identity in original_ids:
            a, b = sequence_rows["tiny416"][identity], sequence_rows["tiny640"][identity]
            if (a["gt"], a["small_gt"]) != (b["gt"], b["small_gt"]):
                raise ValueError("Unpaired GT denominator")
            pairs.append({"sequence": sequence, "original_gt_id": identity, "fps": fps, "tiny416": a, "tiny640": b,
                          "lifetime_cohort": cohort(a["tp"], b["tp"]), "small_cohort": cohort(a["small_tp"], b["small_tp"])})
    rows = []
    for sequence in [*SEQUENCES, "COMBINED"]:
        selected = pairs if sequence == "COMBINED" else [p for p in pairs if p["sequence"] == sequence]
        for scope in ("all_gt", "small_gt_lifetime", "small_observations"):
            for category in ("all", *COHORTS):
                for model in MODELS:
                    rows.append({"sequence": sequence, **aggregate(selected, model, scope, category)})
    result = {"scope": "posthoc_paired_calibration_diagnostics_not_independent_validation",
              "prior_quality_gate": "FAIL_preserved", "trackeval_commit": commit,
              "source_sha256": source_hashes, "official_CLEAR": official,
              "summary": rows, "duration_scope": "full_eligible_GT_lifetime_with_GT_absence_breaks",
              "percentiles": "nearest_rank_unweighted_segment_distribution"}
    for name, value in (("continuity.json", result), ("per-gt-trajectories.json", pairs)):
        with (args.output_dir / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with (args.output_dir / "continuity.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("paired_continuity=PASS; no inference, tuning or holdout; prior FAIL unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
