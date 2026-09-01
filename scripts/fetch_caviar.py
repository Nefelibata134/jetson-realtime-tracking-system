#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from caviar_protocol import (
    load_json,
    read_ground_truth_frames,
    sha256_file,
    validate_dataset_config,
)


def selected_sequences(
    config: dict,
    split: str,
    sequence_ids: set[str],
) -> list[dict]:
    available = {sequence["sequence_id"] for sequence in config["sequences"]}
    unknown = sequence_ids - available
    if unknown:
        raise ValueError("unknown CAVIAR sequences: " + ", ".join(sorted(unknown)))
    return [
        sequence
        for sequence in config["sequences"]
        if (split == "all" or sequence["split"] == split)
        and (not sequence_ids or sequence["sequence_id"] in sequence_ids)
    ]


def download_asset(url: str, destination: Path, expected_sha256: str | None) -> str:
    if destination.is_file():
        checksum = sha256_file(destination)
        if expected_sha256 is None or checksum == expected_sha256:
            print(f"reuse={destination} sha256={checksum}")
            return checksum
        raise ValueError(f"existing asset checksum mismatch: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "edge-vision/1.0"})
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                with temporary.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
            checksum = sha256_file(temporary)
            if expected_sha256 is not None and checksum != expected_sha256:
                raise ValueError(f"downloaded asset checksum mismatch: {destination}")
            os.replace(temporary, destination)
            print(
                f"downloaded={destination} bytes={destination.stat().st_size} "
                f"sha256={checksum}"
            )
            return checksum
        except (OSError, urllib.error.URLError, ValueError) as error:
            last_error = error
            temporary.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(attempt)
    raise ValueError(f"failed to download {url}: {last_error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download the fixed CAVIAR external-validation selection"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("configs/caviar/dataset.json")
    )
    parser.add_argument("--root", type=Path, default=Path("data/caviar"))
    parser.add_argument(
        "--split", choices=("all", "development", "holdout"), default="all"
    )
    parser.add_argument("--sequence", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_json(args.config)
        validate_dataset_config(config)
        sequences = selected_sequences(config, args.split, set(args.sequence))
        if not sequences:
            raise ValueError("no CAVIAR sequences were selected")

        lock_records = []
        for sequence in sequences:
            assets = {}
            for asset_name in ("video", "annotation"):
                asset = sequence[asset_name]
                destination = args.root / asset["relative_path"]
                checksum = download_asset(
                    asset["url"], destination, asset.get("sha256")
                )
                assets[asset_name] = {
                    "path": destination.as_posix(),
                    "url": asset["url"],
                    "bytes": destination.stat().st_size,
                    "sha256": checksum,
                }

            dataset = config["dataset"]
            xml_name, frames = read_ground_truth_frames(
                args.root / sequence["annotation"]["relative_path"],
                frame_width=dataset["frame_width"],
                frame_height=dataset["frame_height"],
            )
            if xml_name != sequence["sequence_id"]:
                raise ValueError(
                    f"annotation dataset name mismatch: expected "
                    f"{sequence['sequence_id']}, found {xml_name}"
                )
            lock_records.append(
                {
                    "sequence_id": sequence["sequence_id"],
                    "split": sequence["split"],
                    "frame_count": len(frames),
                    "first_frame": frames[0].number,
                    "last_frame": frames[-1].number,
                    "assets": assets,
                }
            )

        lock = {
            "schema_version": 1,
            "config": args.config.as_posix(),
            "sequences": lock_records,
        }
        lock_path = args.root / "download-lock.json"
        lock_path.write_text(
            json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except ValueError as error:
        print(f"CAVIAR download failed: {error}")
        return 1

    print(f"download_lock={lock_path}")
    print(f"status=PASS sequences={len(lock_records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
