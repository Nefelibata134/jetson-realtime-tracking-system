#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import re
from pathlib import Path


SEQUENCE_PATTERN = re.compile(r"MOT17-\d{2}-FRCNN")
PUBLIC_TRAIN_SEQUENCES = {
    "MOT17-02-FRCNN",
    "MOT17-04-FRCNN",
    "MOT17-05-FRCNN",
    "MOT17-09-FRCNN",
    "MOT17-10-FRCNN",
    "MOT17-11-FRCNN",
    "MOT17-13-FRCNN",
}
CALIBRATION_SEQUENCES = {
    "MOT17-02-FRCNN",
    "MOT17-04-FRCNN",
    "MOT17-05-FRCNN",
    "MOT17-10-FRCNN",
}


def read_sequence_map(path: Path) -> list[str]:
    if not path.is_file():
        raise ValueError(f"sequence map does not exist: {path}")

    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    if not lines or lines[0] != "name":
        raise ValueError(f"sequence map must start with the 'name' header: {path}")

    sequences = lines[1:]
    if not sequences:
        raise ValueError(f"sequence map does not select any sequences: {path}")
    if len(sequences) != len(set(sequences)):
        raise ValueError(f"sequence map contains duplicate entries: {path}")

    invalid = [
        name
        for name in sequences
        if SEQUENCE_PATTERN.fullmatch(name) is None
        or name not in PUBLIC_TRAIN_SEQUENCES
    ]
    if invalid:
        raise ValueError("unsupported sequence names: " + ", ".join(invalid))
    return sequences


def read_sequence_info(path: Path) -> tuple[int, str, str]:
    parser = configparser.ConfigParser()
    try:
        with path.open() as handle:
            parser.read_file(handle)
        section = parser["Sequence"]
        length = section.getint("seqLength")
        image_directory = section.get("imDir", "img1")
        image_extension = section.get("imExt", ".jpg")
    except (OSError, KeyError, ValueError, configparser.Error) as error:
        raise ValueError(f"invalid sequence metadata: {path}: {error}") from error

    if length <= 0:
        raise ValueError(f"seqLength must be positive: {path}")
    if Path(image_directory).is_absolute() or ".." in Path(image_directory).parts:
        raise ValueError(f"unsafe imDir in sequence metadata: {path}")
    if not image_extension.startswith("."):
        raise ValueError(f"imExt must start with a dot: {path}")
    return length, image_directory, image_extension


def validate_sequence(train_root: Path, sequence: str) -> int:
    sequence_root = train_root / sequence
    info_path = sequence_root / "seqinfo.ini"
    ground_truth_path = sequence_root / "gt" / "gt.txt"

    if not info_path.is_file():
        raise ValueError(f"missing seqinfo.ini: {info_path}")
    if not ground_truth_path.is_file() or ground_truth_path.stat().st_size == 0:
        raise ValueError(f"missing or empty ground truth: {ground_truth_path}")

    length, image_directory, image_extension = read_sequence_info(info_path)
    image_root = sequence_root / image_directory
    if not image_root.is_dir():
        raise ValueError(f"missing image directory: {image_root}")

    images = sorted(image_root.glob(f"*{image_extension}"))
    if len(images) != length:
        raise ValueError(
            f"frame count mismatch for {sequence}: "
            f"seqLength={length}, files={len(images)}"
        )

    first_frame = image_root / f"{1:06d}{image_extension}"
    last_frame = image_root / f"{length:06d}{image_extension}"
    if not first_frame.is_file() or not last_frame.is_file():
        raise ValueError(
            f"frame numbering is incomplete for {sequence}: "
            f"expected {first_frame.name} through {last_frame.name}"
        )
    return length


def validate_dataset(
    train_root: Path, sequence_map: Path, *, calibration_only: bool = False
) -> dict[str, int]:
    sequences = read_sequence_map(sequence_map)
    if calibration_only and not set(sequences) <= CALIBRATION_SEQUENCES:
        raise ValueError("candidate inference is restricted to calibration sequences")
    if not train_root.is_dir():
        raise ValueError(f"MOT17 training directory does not exist: {train_root}")

    results: dict[str, int] = {}
    for sequence in sequences:
        results[sequence] = validate_sequence(train_root, sequence)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate selected MOT17 sequences")
    parser.add_argument("--train-root", type=Path, required=True)
    parser.add_argument("--seqmap", type=Path, required=True)
    parser.add_argument("--calibration-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        results = validate_dataset(
            args.train_root, args.seqmap, calibration_only=args.calibration_only
        )
    except ValueError as error:
        print(f"MOT17 validation failed: {error}")
        return 1

    for sequence, frame_count in results.items():
        print(f"PASS {sequence} frames={frame_count}")
    print(f"status=PASS sequences={len(results)} frames={sum(results.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
