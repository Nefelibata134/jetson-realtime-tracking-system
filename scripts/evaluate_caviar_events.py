#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from caviar_protocol import (
    load_json,
    read_jsonl,
    sequence_by_id,
    validate_dataset_config,
    validate_rules_config,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare runtime events with frozen CAVIAR event truth"
    )
    parser.add_argument(
        "--dataset-config",
        type=Path,
        default=Path("configs/caviar/dataset.json"),
    )
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, default=Path("."))
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    return parser.parse_args()


def anchor(record: dict[str, Any]) -> tuple[float, float]:
    value = record.get("anchor")
    if not isinstance(value, dict):
        raise ValueError("event record is missing anchor")
    x = value.get("x")
    y = value.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        raise ValueError("event anchor coordinates must be numeric")
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("event anchor coordinates must be finite")
    return float(x), float(y)


def frame_number(record: dict[str, Any]) -> int:
    value = record.get("frame_sequence")
    if not isinstance(value, int) or value < 0:
        raise ValueError("event frame_sequence must be a nonnegative integer")
    return value


def evidence_file_exists(value: Any, root: Path, actual_path: Path) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    candidates = (
        [path] if path.is_absolute() else [root / path, actual_path.parent / path]
    )
    return any(
        candidate.is_file() and candidate.stat().st_size > 0 for candidate in candidates
    )


def match_events(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    *,
    frame_tolerance: int,
    anchor_tolerance: float,
) -> tuple[list[dict[str, Any]], list[int], list[int]]:
    candidates: list[tuple[float, int, int, int, float]] = []
    for expected_index, expected_event in enumerate(expected):
        expected_frame = frame_number(expected_event)
        expected_anchor = anchor(expected_event)
        for actual_index, actual_event in enumerate(actual):
            if actual_event.get("event_type") != expected_event.get("event_type"):
                continue
            if expected_event.get("event_type") == "line_crossing" and (
                actual_event.get("direction") != expected_event.get("direction")
            ):
                continue
            actual_frame = frame_number(actual_event)
            actual_anchor = anchor(actual_event)
            frame_delta = abs(actual_frame - expected_frame)
            anchor_delta = math.hypot(
                actual_anchor[0] - expected_anchor[0],
                actual_anchor[1] - expected_anchor[1],
            )
            if frame_delta > frame_tolerance or anchor_delta > anchor_tolerance:
                continue
            normalized_frame = frame_delta / max(frame_tolerance, 1)
            normalized_anchor = anchor_delta / max(anchor_tolerance, 1.0e-9)
            candidates.append(
                (
                    normalized_frame + normalized_anchor,
                    expected_index,
                    actual_index,
                    frame_delta,
                    anchor_delta,
                )
            )

    matched_expected: set[int] = set()
    matched_actual: set[int] = set()
    matches: list[dict[str, Any]] = []
    for _, expected_index, actual_index, frame_delta, anchor_delta in sorted(
        candidates
    ):
        if expected_index in matched_expected or actual_index in matched_actual:
            continue
        matched_expected.add(expected_index)
        matched_actual.add(actual_index)
        matches.append(
            {
                "expected_index": expected_index,
                "actual_index": actual_index,
                "frame_delta": frame_delta,
                "anchor_distance": anchor_delta,
                "expected_frame": frame_number(expected[expected_index]),
                "actual_frame": frame_number(actual[actual_index]),
            }
        )
    false_negatives = [
        index for index in range(len(expected)) if index not in matched_expected
    ]
    false_positives = [
        index for index in range(len(actual)) if index not in matched_actual
    ]
    return matches, false_negatives, false_positives


def ratio(numerator: int, denominator: int, *, empty_value: float) -> float:
    return numerator / denominator if denominator else empty_value


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    evidence = report["evidence"]
    lines = [
        "# CAVIAR 外部事件验证结果",
        "",
        f"**状态：{report['status']}**",
        "",
        "| 序列 | 划分 | 角色 | 事件 | TP | FP | FN | Precision | Recall | F1 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {report['sequence_id']} | {report['split']} | "
            f"{report['validation_role']} | {report['event_type']} | "
            f"{metrics['true_positives']} | "
            f"{metrics['false_positives']} | {metrics['false_negatives']} | "
            f"{metrics['precision']:.3f} | {metrics['recall']:.3f} | "
            f"{metrics['f1']:.3f} |"
        ),
        "",
        "| 实际事件 | 完整截图 | 完整片段 | 证据完整率 | 未评分的其他事件 |",
        "| ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {evidence['actual_events']} | {evidence['valid_snapshots']} | "
            f"{evidence['valid_clips']} | {evidence['complete_ratio']:.3f} | "
            f"{report['unscored_actual_events']} |"
        ),
        "",
        (
            "事件采用帧容差和锚点距离进行一对一匹配；预测 track ID 不与 "
            "CAVIAR 标注 ID 强行对应。"
        ),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        dataset_config = load_json(args.dataset_config)
        validate_dataset_config(dataset_config)
        rules_config = load_json(args.rules)
        validate_rules_config(rules_config, dataset_config, require_frozen=True)
        sequence = sequence_by_id(dataset_config, args.sequence)
        expected_all = read_jsonl(args.expected)
        expected = [
            record
            for record in expected_all
            if record.get("sequence_id") == sequence["sequence_id"]
            and record.get("event_type") == sequence["evaluation_event"]
        ]
        actual_all = read_jsonl(args.actual)
        actual = [
            record
            for record in actual_all
            if record.get("event_type") == sequence["evaluation_event"]
        ]
        matching = rules_config["matching_policy"]
        matches, false_negatives, false_positives = match_events(
            expected,
            actual,
            frame_tolerance=matching["frame_tolerance"],
            anchor_tolerance=matching["anchor_distance_tolerance"],
        )
        true_positives = len(matches)
        precision = ratio(
            true_positives, true_positives + len(false_positives), empty_value=1.0
        )
        recall = ratio(
            true_positives, true_positives + len(false_negatives), empty_value=1.0
        )
        f1 = ratio(2 * precision * recall, precision + recall, empty_value=0.0)

        valid_snapshots = 0
        valid_clips = 0
        complete_evidence = 0
        for record in actual:
            evidence = record.get("evidence")
            if not isinstance(evidence, dict):
                continue
            snapshot_valid = evidence_file_exists(
                evidence.get("snapshot_path"), args.evidence_root, args.actual
            )
            clip_valid = evidence_file_exists(
                evidence.get("clip_path"), args.evidence_root, args.actual
            )
            valid_snapshots += int(snapshot_valid)
            valid_clips += int(clip_valid)
            complete_evidence += int(snapshot_valid and clip_valid)
        complete_ratio = ratio(complete_evidence, len(actual), empty_value=1.0)

        gate_failures = []
        if sequence["split"] == "holdout":
            if precision < matching["minimum_holdout_precision"]:
                gate_failures.append("precision_below_threshold")
            if recall < matching["minimum_holdout_recall"]:
                gate_failures.append("recall_below_threshold")
            if matching["require_complete_evidence"] and complete_ratio < 1.0:
                gate_failures.append("incomplete_event_evidence")
        report_status = (
            "NOT_GATED"
            if sequence["split"] == "development"
            else ("PASS" if not gate_failures else "FAIL")
        )
        report = {
            "schema_version": 1,
            "status": report_status,
            "gate_applied": sequence["split"] == "holdout",
            "gate_failures": gate_failures,
            "sequence_id": sequence["sequence_id"],
            "split": sequence["split"],
            "validation_role": sequence.get("validation_role", "positive_evaluation"),
            "event_type": sequence["evaluation_event"],
            "matching_policy": matching,
            "metrics": {
                "expected_events": len(expected),
                "actual_events": len(actual),
                "true_positives": true_positives,
                "false_positives": len(false_positives),
                "false_negatives": len(false_negatives),
                "precision": precision,
                "recall": recall,
                "f1": f1,
            },
            "evidence": {
                "actual_events": len(actual),
                "valid_snapshots": valid_snapshots,
                "valid_clips": valid_clips,
                "complete_records": complete_evidence,
                "complete_ratio": complete_ratio,
            },
            "matches": matches,
            "false_negative_records": [expected[index] for index in false_negatives],
            "false_positive_records": [actual[index] for index in false_positives],
            "unscored_actual_events": len(actual_all) - len(actual),
        }
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        write_markdown(args.output_markdown, report)
    except ValueError as error:
        print(f"CAVIAR event evaluation failed: {error}")
        return 1

    print(f"status={report['status']}")
    print(f"sequence={sequence['sequence_id']}")
    print(f"precision={precision:.6f}")
    print(f"recall={recall:.6f}")
    print(f"f1={f1:.6f}")
    print(f"report_json={args.output_json}")
    print(f"report_markdown={args.output_markdown}")
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
