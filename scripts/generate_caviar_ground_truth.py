#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from caviar_protocol import (
    generate_events,
    load_json,
    read_ground_truth_frames,
    require_holdout_semantic_audit,
    rules_by_pair,
    sequence_by_id,
    validate_dataset_config,
    validate_rules_config,
    write_jsonl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate event truth from CAVIAR hand-labelled trajectories"
    )
    parser.add_argument(
        "--dataset-config",
        type=Path,
        default=Path("configs/caviar/dataset.json"),
    )
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, default=Path("data/caviar"))
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path)
    return parser.parse_args()


def write_review_markdown(
    path: Path,
    sequence: dict,
    events: list[dict],
    frames_per_second: int,
) -> None:
    lines = [
        f"# {sequence['sequence_id']} 人工真值确认表",
        "",
        f"- 划分：`{sequence['split']}`",
        f"- 目标事件：`{sequence['evaluation_event']}`",
        "- 生成来源：CAVIAR 人工框标注的底边中心轨迹",
        "- 要求：在查看任何系统预测前，对照原视频确认下表。",
        "",
        "| # | 标注 ID | 帧 | 时间 | 锚点 | 方向 | 人工确认 |",
        "| ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for index, event in enumerate(events, 1):
        anchor = event["anchor"]
        seconds = event["frame_sequence"] / frames_per_second
        lines.append(
            f"| {index} | {event['ground_truth_track_id']} | "
            f"{event['frame_sequence']} | {seconds:.2f} s | "
            f"({anchor['x']:.3f}, {anchor['y']:.3f}) | "
            f"{event['direction']} | [ ] |"
        )
    if not events:
        lines.append("| - | - | - | - | - | - | 无事件，必须复核规则是否有意义 |")
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
        require_holdout_semantic_audit(dataset_config, sequence)
        rule = rules_by_pair(rules_config)[sequence["pair_id"]]
        dataset = dataset_config["dataset"]
        xml_path = args.dataset_root / sequence["annotation"]["relative_path"]
        xml_name, frames = read_ground_truth_frames(
            xml_path,
            frame_width=dataset["frame_width"],
            frame_height=dataset["frame_height"],
        )
        if xml_name != sequence["sequence_id"]:
            raise ValueError(
                f"annotation dataset name mismatch: expected "
                f"{sequence['sequence_id']}, found {xml_name}"
            )
        events = generate_events(
            sequence,
            rule,
            frames,
            frames_per_second=dataset["frames_per_second"],
        )
        write_jsonl(args.output, events)
        if args.output_markdown is not None:
            write_review_markdown(
                args.output_markdown,
                sequence,
                events,
                dataset["frames_per_second"],
            )
    except ValueError as error:
        print(f"CAVIAR ground-truth generation failed: {error}")
        return 1

    print(f"sequence={sequence['sequence_id']}")
    print(f"split={sequence['split']}")
    print(f"event_type={sequence['evaluation_event']}")
    print(f"frames={len(frames)}")
    print(f"expected_events={len(events)}")
    print(f"output={args.output}")
    if args.output_markdown is not None:
        print(f"review_markdown={args.output_markdown}")
    print("status=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
