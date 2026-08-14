#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


REQUIRED_FIELDS = ("HOTA", "IDF1", "MOTA", "IDSW")


def parse_summary(path: Path) -> dict[str, float | int]:
    lines = [line.split() for line in path.read_text().splitlines() if line.strip()]
    if len(lines) != 2:
        raise ValueError("TrackEval summary must contain one header and one value row")
    header, values = lines
    if len(header) != len(values):
        raise ValueError("TrackEval summary header and value counts differ")
    raw = dict(zip(header, values))
    missing = [field for field in REQUIRED_FIELDS if field not in raw]
    if missing:
        raise ValueError("TrackEval summary is missing: " + ", ".join(missing))
    return {
        "HOTA": float(raw["HOTA"]),
        "IDF1": float(raw["IDF1"]),
        "MOTA": float(raw["MOTA"]),
        "IDSW": int(raw["IDSW"]),
    }


def render_markdown(
    metrics: dict[str, float | int], summary: Path, title: str
) -> str:
    return "\n".join(
        [
            f"# {title}",
            "",
            "Metrics are computed by the pinned official TrackEval revision.",
            f"Source summary: `{summary.as_posix()}`",
            "",
            "| HOTA | IDF1 | MOTA | ID switches |",
            "| ---: | ---: | ---: | ---: |",
            (
                f"| {metrics['HOTA']:.2f} | {metrics['IDF1']:.2f} | "
                f"{metrics['MOTA']:.2f} | {metrics['IDSW']} |"
            ),
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--title", default="MOT17 Tracking Evaluation")
    args = parser.parse_args()

    metrics = parse_summary(args.summary)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(metrics, indent=2) + "\n")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(metrics, args.summary, args.title))

    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
