#!/usr/bin/env python3
import argparse
import shutil
import time
from pathlib import Path


def directory_size(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file() and not entry.is_symlink():
            total += entry.stat().st_size
    return total


def prune_spool(
    root: Path,
    max_bytes: int,
    max_age_days: float,
    keep_latest: int,
    now: float,
) -> tuple[list[Path], int]:
    root = root.resolve()
    if root == Path(root.anchor) or max_bytes <= 0 or max_age_days <= 0:
        raise ValueError("unsafe spool retention configuration")
    root.mkdir(parents=True, exist_ok=True)

    current_link = root.parent / "current"
    active = current_link.resolve() if current_link.is_symlink() else None
    sessions = sorted(
        (
            path
            for path in root.iterdir()
            if path.is_dir() and not path.is_symlink()
        ),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    sizes = {path: directory_size(path) for path in sessions}
    retained = set(sessions[-keep_latest:]) if keep_latest else set()
    if active is not None and active.parent == root:
        retained.add(active)

    age_limit_seconds = max_age_days * 24.0 * 60.0 * 60.0
    removed: list[Path] = []
    total_bytes = sum(sizes.values())
    for session in sessions:
        if session in retained:
            continue
        expired = now - session.stat().st_mtime > age_limit_seconds
        over_budget = total_bytes > max_bytes
        if not expired and not over_budget:
            continue
        size = sizes[session]
        shutil.rmtree(session)
        removed.append(session)
        total_bytes -= size

    return removed, total_bytes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, required=True)
    parser.add_argument("--max-age-days", type=float, default=7.0)
    parser.add_argument("--keep-latest", type=int, default=1)
    args = parser.parse_args()
    if args.keep_latest < 1:
        parser.error("--keep-latest must be positive")

    removed, retained_bytes = prune_spool(
        args.root,
        args.max_bytes,
        args.max_age_days,
        args.keep_latest,
        time.time(),
    )
    print(f"removed_sessions={len(removed)}")
    print(f"retained_bytes={retained_bytes}")


if __name__ == "__main__":
    main()
