#!/usr/bin/env python3
from __future__ import annotations

import json
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
    "docs/licensing.md",
    "docs/models/yolo26s.md",
    "docs/benchmarks/jetson_full_pipeline_matrix.md",
    "docs/benchmarks/mot17_tracking_results.md",
    "docs/operations/headless_service.md",
    "docs/operations/stability_report.md",
    "docs/releases/v1.0.0.md",
    "models/yolo26s.json",
    "requirements/yolo26-export.txt",
    "scripts/export_yolo26s_onnx.py",
    "scripts/fetch_yolo26s.sh",
}
REQUIRED_README_HEADINGS = {
    "Jetson 实机实测",
    "运行证据",
    "运行时架构",
    "Jetson 快速开始",
    "组件",
    "目标平台",
    "模型资产",
    "许可证",
}
FORBIDDEN_TEXT = re.compile(
    "Day\\s*\\d+|\\u5b66\\u4e60|\\u7ec3\\u4e60|\\u590d\\u4e60|"
    "\\u6559\\u7a0b|\\u8bfe\\u7a0b\\u4f5c\\u4e1a|\\u6253\\u5361|"
    "\\u6c42\\u804c|\\u62db\\u8058|\\u7b80\\u5386|\\u4f5c\\u54c1\\u96c6|"
    "\\u9762\\u8bd5\\u51c6\\u5907|\\u9762\\u8bd5\\u5b98|"
    "\\u7528\\u4e8e\\u5c55\\u793a|\\x43odex|\\x43hatGPT|"
    "\\x41\\x49\\s*\\u534f\\u4f5c|\\u804a\\u5929\\u8fc7\\u7a0b|"
    "\\u7528\\u6237\\u80cc\\u666f|\\u5185\\u90e8\\u4ea4\\u63a5|"
    "\\u4e0b\\u4e00\\u6b21\\u5bf9\\u8bdd",
    re.IGNORECASE,
)
FORBIDDEN_SUFFIXES = {
    ".avi",
    ".engine",
    ".log",
    ".mp4",
    ".onnx",
    ".plan",
    ".pt",
    ".pth",
    ".weights",
}
FORBIDDEN_PREFIXES = (
    ".cache/",
    ".venv-yolo26-export/",
    "build/",
    "credentials/",
    "data/",
    "external/",
    "outputs/",
    "reports/",
)
YOLO26_WEIGHT_SHA256 = (
    "646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b"
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def is_forbidden_artifact(path: str) -> bool:
    name = Path(path).name.lower()
    return (
        path.startswith(FORBIDDEN_PREFIXES)
        or Path(path).suffix.lower() in FORBIDDEN_SUFFIXES
        or name.endswith(".onnx.data")
        or name == ".env"
        or name.startswith(".env.")
    )


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
        failures.append("缺少必须纳入版本控制的文件：" + ", ".join(missing_required))

    cmake = (root / "CMakeLists.txt").read_text(encoding="utf-8")
    version_match = re.search(
        r"project\(jetson_realtime_tracking_system\s+VERSION\s+([0-9.]+)", cmake
    )
    if version_match is None or version_match.group(1) != EXPECTED_VERSION:
        failures.append(f"CMake 项目版本不是 {EXPECTED_VERSION}")

    readme = (root / "README.md").read_text(encoding="utf-8")
    headings = set(re.findall(r"^##\s+(.+?)\s*$", readme, re.MULTILINE))
    missing_headings = sorted(REQUIRED_README_HEADINGS - headings)
    if missing_headings:
        failures.append("README 缺少章节：" + ", ".join(missing_headings))

    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    if (
        "GNU AFFERO GENERAL PUBLIC LICENSE" not in license_text
        or "Version 3, 19 November 2007" not in license_text
        or "AGPL-3.0-only" not in readme
    ):
        failures.append("项目许可证不是声明的 AGPL-3.0-only")

    forbidden_artifacts = sorted(
        path
        for path in files
        if is_forbidden_artifact(path)
    )
    if forbidden_artifacts:
        failures.append("运行产物被纳入版本控制：" + ", ".join(forbidden_artifacts))

    scan_suffixes = {".cpp", ".hpp", ".md", ".py", ".sh", ".txt", ".yml", ".yaml"}
    for relative in files:
        path = root / relative
        if relative.startswith("third_party/") or path.suffix.lower() not in scan_suffixes:
            continue
        match = FORBIDDEN_TEXT.search(path.read_text(encoding="utf-8"))
        if match:
            failures.append(f"{relative} 包含仓库禁用文本：{match.group(0)}")

    for relative in files:
        path = root / relative
        if path.suffix.lower() != ".md":
            continue
        for missing in local_markdown_links(path):
            failures.append(f"{relative} 包含失效的本地 Markdown 链接：{missing}")

    metadata = json.loads((root / "models/yolo26s.json").read_text(encoding="utf-8"))
    if (
        metadata.get("upstream", {}).get("weight_asset_release") != "v8.4.0"
        or metadata.get("upstream", {}).get("source_code_tag") != "v8.4.138"
        or metadata.get("upstream", {}).get("source_code_commit")
        != "dad7bb4534c95021bc14969ab25d77b77c4efdc3"
        or metadata.get("upstream", {}).get("license") != "AGPL-3.0"
        or metadata.get("weight", {}).get("sha256") != YOLO26_WEIGHT_SHA256
        or metadata.get("weight", {}).get("tracked") is not False
        or metadata.get("export", {}).get("version") != "8.4.138"
        or metadata.get("export", {}).get("end2end") is not False
        or metadata.get("host_export_verification", {}).get("repeat_hash_equal")
        is not True
        or metadata.get("host_export_verification", {}).get(
            "jetson_engine_validated"
        )
        is not False
    ):
        failures.append("YOLO26s 来源、许可证、哈希或导出契约不符合固定元数据")

    for relative in (
        "THIRD_PARTY_NOTICES.md",
        "docs/models/yolo26s.md",
        "scripts/export_yolo26s_onnx.py",
        "scripts/fetch_yolo26s.sh",
    ):
        if YOLO26_WEIGHT_SHA256 not in (root / relative).read_text(encoding="utf-8"):
            failures.append(f"{relative} 未包含固定的 YOLO26s 权重哈希")

    return failures


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        failures = validate(root)
    except (OSError, subprocess.CalledProcessError, UnicodeError) as error:
        print(f"FAIL 无法检查仓库：{error}")
        return 1
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
