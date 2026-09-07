#!/usr/bin/env python3
"""Four fixed calibration candidates: paired GT continuity without inference or tuning."""
from __future__ import annotations

import argparse
import configparser
import csv
import itertools
import json
from pathlib import Path
import subprocess
import sys

from analyze_mot17_continuity import aggregate, cohort, match_existing, trajectory
from diagnose_mot17_height import SEQUENCES, TRACKEVAL_COMMIT, freeze
from export_yolox_tiny_onnx import sha256

MODELS = ("tiny416", "tiny640", "t35_n35_m80", "t30_n45_m75")
SCOPES = ("all_gt", "small_gt_lifetime", "small_observations")
CATEGORIES = {"all": "all", "both": "common", "tiny640_only": "candidate_only",
              "tiny416_only": "reference_only", "neither": "neither"}


def validate_records(records):
    seen = set()
    for record in records:
        key = record["sequence"], record["original_gt_id"]
        if key in seen or record["sequence"] not in SEQUENCES:
            raise ValueError("Duplicate or non-calibration GT identity")
        seen.add(key)
        if set(record["models"]) != set(MODELS):
            raise ValueError("Require the four fixed candidates")
        denominator = None
        for model in MODELS:
            value = record["models"][model]
            current = (value["gt"], value["small_gt"], value["gt_seconds"], value["gt_segments"])
            if denominator is not None and current != denominator:
                raise ValueError("Unpaired GT denominator")
            denominator = current
            for field, count in (("matched_frames", "tp"), ("small_matched_frames", "small_tp")):
                if len(value[field]) != len(set(value[field])) or len(value[field]) != value[count]:
                    raise ValueError("Matched frame accounting mismatch")
            if not set(value["small_matched_frames"]) <= set(value["matched_frames"]):
                raise ValueError("Small matches must be a subset of all matches")


def paired_summary(records, reference, candidate, scope, category="all"):
    if reference not in MODELS or candidate not in MODELS or reference == candidate:
        raise ValueError("Invalid fixed pair")
    if scope not in SCOPES or category not in CATEGORIES:
        raise ValueError("Invalid diagnostic scope or cohort")
    pairs = []
    for record in records:
        a, b = (record["models"][m] for m in (reference, candidate))
        pairs.append({"tiny416": a, "tiny640": b,
                      "lifetime_cohort": cohort(a["tp"], b["tp"]),
                      "small_cohort": cohort(a["small_tp"], b["small_tp"])})
    basis = "small_cohort" if scope == "small_observations" else "lifetime_cohort"
    selected = [p for p in pairs if (scope == "all_gt" or p["tiny416"]["small_gt"] > 0)
                and (category == "all" or p[basis] == category)]
    frames = "small_matched_frames" if scope == "small_observations" else "matched_frames"
    shared, gained, lost = 0, 0, 0
    for pair in selected:
        a, b = (set(pair[m][frames]) for m in ("tiny416", "tiny640"))
        shared += len(a & b)
        gained += len(b - a)
        lost += len(a - b)
    common = {"reference": reference, "candidate": candidate,
              "shared_matched_observations": shared,
              "candidate_gained_observations": gained, "candidate_lost_observations": lost}
    # Compare each GT identity, not only distributions from changing trajectory populations.
    for field in ("coverage", "longest_matched_seconds", "longest_same_identity_seconds"):
        lookup = "small_coverage" if field == "coverage" and scope == "small_observations" else field
        deltas = [p["tiny640"][lookup] - p["tiny416"][lookup] for p in selected]
        common.update({field + "_gt_increased": sum(d > 1e-12 for d in deltas),
                       field + "_gt_decreased": sum(d < -1e-12 for d in deltas),
                       field + "_gt_unchanged": sum(abs(d) <= 1e-12 for d in deltas)})
    output = []
    for alias, model in (("tiny416", reference), ("tiny640", candidate)):
        row = aggregate(pairs, alias, scope, category)
        row.update(common)
        row.update(model=model, cohort=CATEGORIES[category])
        expected = shared + (lost if model == reference else gained)
        if expected != row["matched_observations"]:
            raise ValueError("Paired observation accounting mismatch")
        output.append(row)
    return output


def four_way_summary(records, scope):
    if scope not in SCOPES:
        raise ValueError("Invalid scope")
    tp_key = "small_tp" if scope == "small_observations" else "tp"
    eligible = [r for r in records if scope == "all_gt" or r["models"][MODELS[0]]["small_gt"] > 0]
    masks = {"".join(bits): 0 for bits in itertools.product("01", repeat=4)}
    for record in eligible:
        masks["".join("1" if record["models"][m][tp_key] else "0" for m in MODELS)] += 1
    rows = []
    for category in ("all", "all_four_covered"):
        selected = eligible if category == "all" else [r for r in eligible if all(r["models"][m][tp_key] for m in MODELS)]
        for model in MODELS:
            aliases = [{"tiny416": r["models"][model], "lifetime_cohort": "both", "small_cohort": "both"} for r in selected]
            row = aggregate(aliases, "tiny416", scope)
            row.update(model=model, cohort=category,
                       cohort_basis="four_way_small_match" if scope == "small_observations" else "four_way_lifetime_match")
            rows.append(row)
    return rows, masks


def load_manifest(path):
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if set(manifest["models"]) != set(MODELS):
        raise ValueError("Require exactly four fixed models; no parameter search")
    for model in MODELS:
        item = manifest["models"][model]
        if set(item["files"]) != set(SEQUENCES) or set(item["official_CLEAR"]) != set(SEQUENCES):
            raise ValueError("Require exactly four calibration sequences")
        for sequence, info in item["files"].items():
            file = Path(info["path"])
            if file.name != sequence + ".txt" or not file.is_file() or file.is_symlink():
                raise ValueError("Invalid calibration track file")
            if sha256(file) != info["sha256"]:
                raise ValueError("Tracking input hash mismatch")
            if file.parent.name != "data" or file.parent.parent.name != item["tracker_id"]:
                raise ValueError("TrackEval directory contract changed")
    return manifest


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--trackeval", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = load_manifest(args.manifest)
    if freeze(args.data_root) != json.loads(args.protocol.read_text(encoding="utf-8")):
        raise ValueError("Frozen GT/seqinfo/calibration protocol changed")
    git = ["git", "-c", f"safe.directory={args.trackeval.resolve()}", "-C", str(args.trackeval)]
    if subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip() != TRACKEVAL_COMMIT:
        raise ValueError("TrackEval commit changed")
    if subprocess.check_output(git + ["status", "--porcelain"], text=True).strip():
        raise ValueError("TrackEval is dirty")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(args.trackeval.resolve()))
    from trackeval.datasets import MotChallenge2DBox
    records, official = [], {}
    for sequence in SEQUENCES:
        info = configparser.ConfigParser()
        info.read(args.data_root / sequence / "seqinfo.ini")
        fps = float(info["Sequence"]["frameRate"])
        gt = {}
        with (args.data_root / sequence / "gt/gt.txt").open() as stream:
            for row in csv.reader(stream):
                if int(row[6]) != 0 and int(row[7]) == 1:
                    gt.setdefault(int(row[1]), {})[int(row[0]) - 1] = tuple(map(float, row[2:6]))
        ids, sequence_models = sorted(gt), {}
        official[sequence] = {}
        for model in MODELS:
            item = manifest["models"][model]
            root = Path(item["files"][sequence]["path"]).parent.parent.parent
            dataset = MotChallenge2DBox({"GT_FOLDER": str(args.data_root), "TRACKERS_FOLDER": str(root),
                "TRACKERS_TO_EVAL": [item["tracker_id"]], "SEQ_INFO": SEQUENCES, "SKIP_SPLIT_FOL": True,
                "DO_PREPROC": True, "PRINT_CONFIG": False, "BENCHMARK": "MOT17", "SPLIT_TO_EVAL": "train"})
            data = dataset.get_preprocessed_seq_data(dataset.get_raw_seq_data(item["tracker_id"], sequence), "pedestrian")
            matches, metrics = match_existing(data)
            if metrics != item["official_CLEAR"][sequence]:
                raise ValueError("Official CLEAR reconciliation failed: " + sequence + "/" + model)
            official[sequence][model] = metrics
            observations = {identity: [] for identity in ids}
            for t, (mapped, boxes) in enumerate(zip(data["gt_ids"], data["gt_dets"])):
                for index, (mapped_id, box) in enumerate(zip(mapped, boxes)):
                    identity = ids[int(mapped_id)]
                    if tuple(map(float, box)) != gt[identity][t]:
                        raise ValueError("Original GT geometry or ID changed")
                    observations[identity].append((t, float(box[3]), matches.get(t, {}).get(index)))
            sequence_models[model] = {}
            for identity, observed in observations.items():
                result = trajectory(observed, fps)
                result["matched_frames"] = [r[0] for r in observed if r[2] is not None]
                result["small_matched_frames"] = [r[0] for r in observed if r[2] is not None and r[1] < 100]
                sequence_models[model][identity] = result
            if sum(r["tp"] for r in sequence_models[model].values()) != metrics["CLR_TP"]:
                raise ValueError("Per-GT matches differ from official CLEAR")
        records.extend({"sequence": sequence, "original_gt_id": identity, "fps": fps,
                        "models": {m: sequence_models[m][identity] for m in MODELS}} for identity in ids)
        print("continuity_sequence=" + sequence, flush=True)
    validate_records(records)
    rows, four_rows, masks = [], [], {}
    for sequence in [*SEQUENCES, "COMBINED"]:
        selected = records if sequence == "COMBINED" else [r for r in records if r["sequence"] == sequence]
        masks[sequence] = {}
        for scope in SCOPES:
            four, mask = four_way_summary(selected, scope)
            four_rows.extend({"sequence": sequence, **row} for row in four)
            masks[sequence][scope] = mask
            for reference, candidate in itertools.combinations(MODELS, 2):
                for category in CATEGORIES:
                    rows.extend({"sequence": sequence, **row} for row in paired_summary(selected, reference, candidate, scope, category))
    result = {"schema_version": 1, "scope": "posthoc_calibration_diagnostics_not_independent_validation",
              "prior_gate": "FAIL_preserved", "models": list(MODELS), "trackeval_commit": TRACKEVAL_COMMIT,
              "input_manifest_sha256": sha256(args.manifest), "gt_protocol_sha256": sha256(args.protocol),
              "implementation_sha256": {name: sha256(Path(__file__).parent / name) for name in
                  ("compare_mot17_continuity.py", "analyze_mot17_continuity.py", "diagnose_mot17_height.py")},
              "source_sha256": {m: {s: manifest["models"][m]["files"][s]["sha256"] for s in SEQUENCES} for m in MODELS},
              "official_CLEAR": official, "summary": rows, "four_way_summary": four_rows, "coverage_masks": masks,
              "duration_scope": "full_eligible_GT_lifetime_with_GT_absence_breaks",
              "percentiles": "nearest_rank_unweighted_segments_not_overall_pipeline_latency",
              "cohort_limitation": "posthoc_outcome_conditioned_not_causal; always retain all_GT_denominator",
              "CAVIAR": "NOT_RUN", "new_device_replay_verification": "NOT_RUN"}
    # Raw per-GT material belongs in the ignored run directory, not the public repository.
    write_json(args.output_dir / "per-gt-trajectories.json", records)
    write_json(args.output_dir / "continuity.json", result)
    for name, values in (("paired.csv", rows), ("four-way.csv", four_rows)):
        with (args.output_dir / name).open("x", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows(values)
    load_manifest(args.manifest)
    print("four_candidate_continuity=PASS; no tuning, inference, holdout or device operations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
