#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


EXPECTED_VERSION = "1.0.0"
REQUIRED_FILES = {
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "docs/benchmarks/jetson_full_pipeline_matrix.md",
    "docs/benchmarks/mot17_tracking_results.md",
    "docs/operations/headless_service.md",
    "docs/operations/stability_report.md",
    "docs/releases/v1.0.0.md",
}
REQUIRED_README_HEADINGS = {
    "Measured On Jetson",
    "Runtime Evidence",
    "Runtime Architecture",
    "Quick Start On Jetson",
    "Components",
    "Target Platform",
    "Model Artifacts",
    "License",
}
FORBIDDEN_TEXT = re.compile(
    "Day\\s*\\d+|\\u5b66\\u4e60|\\u6559\\u7a0b|\\u6253\\u5361|"
    "\\u62db\\u8058|\\u7b80\\u5386|\\u4f5c\\u54c1\\u96c6|"
    "\\u9762\\u8bd5\\u5b98",
    re.IGNORECASE,
)
FORBIDDEN_SUFFIXES = {".avi", ".engine", ".log", ".mp4", ".onnx", ".plan", ".pth"}
FORBIDDEN_PREFIXES = ("build/", "data/", "external/", "outputs/", "reports/")
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [entry.decode() for entry in result.stdout.split(b"\0") if entry]


def local_markdown_links(path: Path) -> list[Path]:
    missing = []
    for target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
        target = target.strip().split("#", 1)[0]
        if not target or "://" in target or target.startswith(("#", "mailto:")):
            continue
        candidate = (path.parent / target).resolve()
        if not candidate.exists():
            missing.append(candidate)
    return missing


def validate(root: Path) -> list[str]:
    failures: list[str] = []
    files = tracked_files(root)
    tracked = set(files)

    missing_required = sorted(REQUIRED_FILES - tracked)
    if missing_required:
        failures.append("missing required tracked files: " + ", ".join(missing_required))

    cmake = (root / "CMakeLists.txt").read_text(encoding="utf-8")
    version_match = re.search(
        r"project\(jetson_realtime_tracking_system\s+VERSION\s+([0-9.]+)", cmake
    )
    if version_match is None or version_match.group(1) != EXPECTED_VERSION:
        failures.append(f"CMake project version is not {EXPECTED_VERSION}")

    readme = (root / "README.md").read_text(encoding="utf-8")
    headings = set(re.findall(r"^##\s+(.+?)\s*$", readme, re.MULTILINE))
    missing_headings = sorted(REQUIRED_README_HEADINGS - headings)
    if missing_headings:
        failures.append("README is missing headings: " + ", ".join(missing_headings))

    forbidden_artifacts = sorted(
        path
        for path in files
        if path.startswith(FORBIDDEN_PREFIXES)
        or Path(path).suffix.lower() in FORBIDDEN_SUFFIXES
    )
    if forbidden_artifacts:
        failures.append("tracked runtime artifacts: " + ", ".join(forbidden_artifacts))

    scan_suffixes = {".cpp", ".hpp", ".md", ".py", ".sh", ".txt", ".yml", ".yaml"}
    for relative in files:
        path = root / relative
        if relative.startswith("third_party/") or path.suffix.lower() not in scan_suffixes:
            continue
        match = FORBIDDEN_TEXT.search(path.read_text(encoding="utf-8"))
        if match:
            failures.append(f"forbidden repository text in {relative}: {match.group(0)}")

    for relative in files:
        path = root / relative
        if path.suffix.lower() != ".md":
            continue
        for missing in local_markdown_links(path):
            failures.append(f"broken local Markdown link in {relative}: {missing}")

    return failures


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    failures = validate(root)
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(f"release_version={EXPECTED_VERSION}")
    print("required_files=true")
    print("readme_contract=true")
    print("artifact_boundary=true")
    print("markdown_links=true")
    print("repository_language=true")
    print("status=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
