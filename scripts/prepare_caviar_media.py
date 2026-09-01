#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from caviar_protocol import (
    load_json,
    read_ground_truth_frames,
    sequence_by_id,
    sha256_file,
    validate_dataset_config,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert CAVIAR MPEG2 clips to H.264 MP4 for the Jetson file source"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("configs/caviar/dataset.json")
    )
    parser.add_argument("--root", type=Path, default=Path("data/caviar"))
    parser.add_argument("--sequence", action="append", default=[])
    parser.add_argument("--bitrate-kbps", type=int, default=2500)
    return parser.parse_args()


def build_conversion_command(
    source: Path,
    destination: Path,
    bitrate_kbps: int,
    frames_per_second: int,
) -> list[str]:
    return [
        "gst-launch-1.0",
        "-q",
        "-e",
        "filesrc",
        f"location={source}",
        "!",
        "decodebin",
        "!",
        "nvvidconv",
        "!",
        "video/x-raw,format=I420",
        "!",
        "videorate",
        "!",
        f"video/x-raw,format=I420,framerate={frames_per_second}/1",
        "!",
        "x264enc",
        "tune=zerolatency",
        "speed-preset=ultrafast",
        f"bitrate={bitrate_kbps}",
        "key-int-max=25",
        "!",
        "h264parse",
        "!",
        "mp4mux",
        "!",
        "filesink",
        f"location={destination}",
    ]


def convert(
    source: Path,
    destination: Path,
    bitrate_kbps: int,
    frames_per_second: int,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part.mp4")
    temporary.unlink(missing_ok=True)
    command = build_conversion_command(
        source,
        temporary,
        bitrate_kbps,
        frames_per_second,
    )
    print("command=" + " ".join(str(item) for item in command))
    subprocess.run(command, check=True)
    if not temporary.is_file() or temporary.stat().st_size == 0:
        raise ValueError(f"GStreamer produced an empty file: {temporary}")
    temporary.replace(destination)


def validate_prepared_video(path: Path) -> None:
    subprocess.run(
        [
            "gst-launch-1.0",
            "-q",
            "filesrc",
            f"location={path}",
            "!",
            "qtdemux",
            "!",
            "h264parse",
            "!",
            "fakesink",
        ],
        check=True,
    )


def main() -> int:
    args = parse_args()
    try:
        if args.bitrate_kbps <= 0:
            raise ValueError("bitrate-kbps must be positive")
        if shutil.which("gst-launch-1.0") is None:
            raise ValueError("gst-launch-1.0 was not found")
        if shutil.which("gst-inspect-1.0") is None:
            raise ValueError("gst-inspect-1.0 was not found")
        for plugin in ("nvvidconv", "videorate", "x264enc", "h264parse", "mp4mux"):
            subprocess.run(
                ["gst-inspect-1.0", plugin],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )

        config = load_json(args.config)
        validate_dataset_config(config)
        dataset = config["dataset"]
        frames_per_second = dataset["frames_per_second"]
        if args.sequence:
            sequences = [sequence_by_id(config, item) for item in args.sequence]
        else:
            sequences = config["sequences"]

        records = []
        for sequence in sequences:
            source = args.root / sequence["video"]["relative_path"]
            if not source.is_file() or source.stat().st_size == 0:
                raise ValueError(f"missing raw CAVIAR video: {source}")
            destination = (
                args.root / "prepared" / "videos" / f"{sequence['sequence_id']}.mp4"
            )
            annotation = args.root / sequence["annotation"]["relative_path"]
            xml_name, evaluation_frames = read_ground_truth_frames(
                annotation,
                frame_width=dataset["frame_width"],
                frame_height=dataset["frame_height"],
            )
            if xml_name != sequence["sequence_id"]:
                raise ValueError(
                    f"annotation sequence name does not match {sequence['sequence_id']}"
                )
            if not destination.is_file():
                convert(
                    source,
                    destination,
                    args.bitrate_kbps,
                    frames_per_second,
                )
            validate_prepared_video(destination)
            checksum = sha256_file(destination)
            print(
                f"prepared={destination} bytes={destination.stat().st_size} "
                f"sha256={checksum}"
            )
            records.append(
                {
                    "sequence_id": sequence["sequence_id"],
                    "source": source.as_posix(),
                    "prepared": destination.as_posix(),
                    "bytes": destination.stat().st_size,
                    "sha256": checksum,
                    "codec": "H.264",
                    "container": "MP4",
                    "bitrate_kbps": args.bitrate_kbps,
                    "frames_per_second": frames_per_second,
                    "evaluation_frames": len(evaluation_frames),
                }
            )

        lock_path = args.root / "prepared-lock.json"
        lock_path.write_text(
            json.dumps(
                {"schema_version": 1, "videos": records},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"CAVIAR media preparation failed: {error}")
        return 1

    print(f"prepared_lock={lock_path}")
    print(f"status=PASS videos={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
