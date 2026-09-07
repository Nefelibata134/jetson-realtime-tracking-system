#!/usr/bin/env python3
"""原生分辨率配对素材校验、无损降采样与预测前冻结；不执行设备操作。"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "configs/benchmarks/tiny_source_resolution_v5.json"
EVENTS = {"roi_intrusion", "line_crossing", "dwell"}
RULE_IDS = {"roi_intrusion": "restricted-area-entry", "line_crossing": "directional-crossing", "dwell": "restricted-area-dwell"}
SHA = re.compile(r"[a-f0-9]{64}")


def require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(data)
    return value.hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def safe_file(root: Path, name: str) -> Path:
    require(isinstance(name, str) and name and "\\" not in name, "文件名必须是相对 POSIX 路径")
    rel = Path(name)
    require(not rel.is_absolute() and ":" not in name and ".." not in rel.parts, "拒绝目录越界")
    path = root / rel
    require(path.is_file() and path.resolve().is_relative_to(root.resolve()), "文件缺失或越界：" + name)
    require(not any(part.is_symlink() for part in [path, *path.parents] if part != root.parent), "拒绝符号链接输入")
    return path


def checked_file(root: Path, record: dict[str, Any]) -> Path:
    path = safe_file(root, record["path"])
    require(isinstance(record.get("sha256"), str) and SHA.fullmatch(record["sha256"]), "无效 SHA-256")
    require(digest(path) == record["sha256"], "文件哈希不一致：" + record["path"])
    return path


def load_recipe() -> dict[str, Any]:
    config = read(RECIPE)
    require(config["protocol_id"] == "tiny-source-resolution-development-v5", "协议 ID 不一致")
    require(config["native_size"] == [1280, 720] and config["low_size"] == [384, 216], "分辨率改变")
    require(config["fps"] == [30, 1], "帧率改变")
    require(config["thresholds"] == dict(score=.1, nms=.45, track=.3, new_track=.4, match=.8), "五个阈值改变")
    require(config["bytetrack"] == dict(frame_rate=30, buffer=30, second_match=.5, unconfirmed_match=.7), "跟踪设置改变")
    require(config["transform"] == dict(implementation="OpenCV_INTER_AREA", source="decode_each_native_PNG_once",
            pixel_format="BGR8", codec="PNG", png_compression=1, crop=False, letterbox=False, lossy_reencode=False),
            "缩放或编码设置改变")
    require(config["groups"] == [dict(id=s+"_"+m, source=s, model=m)
                                for s in ("native", "low") for m in ("tiny416", "tiny640")], "只允许固定四组")
    return config


def validate_timeline(rows: list[dict[str, Any]], frame_count: int, tolerance_ns: int) -> None:
    require(integer(frame_count, 1) and len(rows) == frame_count, "帧数不完整")
    require(integer(tolerance_ns) and tolerance_ns <= 1000000, "不允许放宽 PTS 容差")
    for index, row in enumerate(rows):
        require(type(row.get("sequence")) is int and row["sequence"] == index, "帧序缺口、重复或重排")
        require(integer(row.get("pts_ns")), "无效 PTS")
        if index:
            require(row["pts_ns"] > rows[index - 1]["pts_ns"], "PTS 不递增")
        require(abs((row["pts_ns"] - rows[0]["pts_ns"]) * 30 - index * 1000000000)
                <= tolerance_ns * 30, "PTS 不符合固定 30 FPS 时间网格")


def validate_provenance(meta: dict[str, Any], root: Path) -> None:
    origin = meta["provenance"]
    require(origin["kind"] in {"authorized_native_video", "csi_native_capture"}, "未知素材来源")
    for key in ("rights_confirmed", "native_720_confirmed", "unannotated", "not_upscaled", "not_holdout"):
        require(origin.get(key) is True, "来源声明未确认：" + key)
    require(bool(origin.get("source_description", "").strip()), "缺少来源说明")
    # 文件与声明只能证明可追溯性；原生来源和使用权仍须由素材持有人审核。
    for key in ("rights_evidence", "acquisition_evidence"):
        checked_file(root, origin[key])
    require(origin.get("reviewed_before_predictions") is True, "来源尚未在预测前审核")
    measurement = meta["acquisition"]
    require(measurement.get("target_reached") is True, "采集未达到目标")
    for key in ("unexpected_dropped_frames", "sequence_gaps", "decode_errors"):
        require(type(measurement.get(key)) is int and measurement[key] == 0, "采集无效：" + key)
    require(integer(measurement.get("warmup_discarded_frames")), "预热计数缺失")
    require(integer(measurement.get("planned_decimated_frames")), "计划降帧计数缺失")
    if origin["kind"] == "csi_native_capture":
        require(measurement.get("sensor_fps") == [60, 1], "CSI 采集必须为 60 FPS")
        require(measurement.get("delivery_fps") == [30, 1], "CSI 交付必须为 30 FPS")


def validate_native(manifest: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    config = load_recipe()
    meta = read(manifest)
    require(meta.get("schema_version") == 1 and meta.get("kind") == "native720_unannotated_frames", "素材 schema 不符")
    require(meta.get("width") == 1280 and meta.get("height") == 720 and meta.get("fps") == [30, 1], "非原生 720p/30 素材")
    require(meta.get("pixel_format") == "BGR8" and meta.get("codec") == "PNG", "输入必须为无标注 BGR8 PNG")
    require(re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", meta.get("clip_id", "")), "无效 clip_id")
    validate_provenance(meta, manifest.parent)
    rows = meta["frames"]
    validate_timeline(rows, meta["frame_count"], config["capture"]["pts_grid_tolerance_ns"])
    require(len({row["path"] for row in rows}) == len(rows), "帧文件被重复引用")
    for row in rows:
        require(row["path"].endswith(".png"), "帧文件必须是 PNG")
        checked_file(manifest.parent, row)
    return meta, rows


def pixels(path: Path, size: list[int]):
    import cv2
    import numpy as np
    value = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    require(value is not None and value.shape == (size[1], size[0], 3) and value.dtype == np.uint8,
            "帧像素格式或尺寸不符：" + str(path))
    return value


def prepare(manifest: Path, output: Path) -> dict[str, Any]:
    import cv2
    import numpy as np
    config = load_recipe()
    meta, rows = validate_native(manifest)
    require(not output.exists(), "拒绝复用输出目录")
    require(not output.resolve().is_relative_to(manifest.parent.resolve()), "输出不能置于源素材目录内")
    output.mkdir(parents=True, exist_ok=False)
    for name in ("native", "low", "source-evidence"):
        (output / name).mkdir()
    # 自包含输入快照，不依赖可变外部目录，不复制录像外的无关文件。
    write_new(output / "source-evidence/native-manifest.json", meta)
    copied_evidence = {}
    for key in ("rights_evidence", "acquisition_evidence"):
        source = checked_file(manifest.parent, meta["provenance"][key])
        target = output / "source-evidence" / (key + ".bin")
        shutil.copyfile(source, target)
        copied_evidence[key] = dict(path=target.relative_to(output).as_posix(), sha256=digest(target))
    pairs = []
    for row in rows:
        source = checked_file(manifest.parent, row)
        native = pixels(source, config["native_size"])
        low = cv2.resize(native, tuple(config["low_size"]), interpolation=cv2.INTER_AREA)
        native_path = output / "native" / (f"{row['sequence']:06d}.png")
        low_path = output / "low" / native_path.name
        shutil.copyfile(source, native_path)
        require(digest(native_path) == row["sha256"], "复制过程中源帧改变")
        require(cv2.imwrite(str(low_path), low, [cv2.IMWRITE_PNG_COMPRESSION, 1]), "PNG 写入失败")
        require(np.array_equal(low, pixels(low_path, config["low_size"])), "低清 PNG 非无损")
        pairs.append(dict(sequence=row["sequence"], pts_ns=row["pts_ns"],
            native=dict(path=native_path.relative_to(output).as_posix(), sha256=digest(native_path)),
            low=dict(path=low_path.relative_to(output).as_posix(), sha256=digest(low_path)),
            native_pixels_sha256=hashlib.sha256(native.tobytes()).hexdigest(),
            low_pixels_sha256=hashlib.sha256(low.tobytes()).hexdigest()))
    require(read(manifest) == meta, "处理过程中源 manifest 改变")
    result = dict(schema_version=1, protocol_id=config["protocol_id"], recipe_sha256=digest(RECIPE),
        kind="paired_source_resolution", clip_id=meta["clip_id"], frame_count=len(rows), fps=[30, 1],
        source_manifest_sha256=digest(output / "source-evidence/native-manifest.json"),
        source_evidence=copied_evidence, transform=config["transform"],
        versions=dict(opencv=cv2.__version__, numpy=np.__version__, python=sys.version.split()[0]),
        frames=pairs, status="PAIRED_NOT_FROZEN")
    write_new(output / "pairs.json", result)
    verify(output / "pairs.json")
    return result


def verify(manifest: Path) -> dict[str, Any]:
    import cv2
    import numpy as np
    config = load_recipe()
    meta = read(manifest)
    require(meta.get("schema_version") == 1 and meta.get("kind") == "paired_source_resolution", "配对 schema 不符")
    require(meta.get("recipe_sha256") == digest(RECIPE), "协议哈希改变")
    require(meta.get("fps") == [30, 1] and meta.get("transform") == config["transform"], "配对设置改变")
    require(meta["versions"]["opencv"] == cv2.__version__, "缩放库版本不同；先使用已记录版本复核")
    source = checked_file(manifest.parent, dict(path="source-evidence/native-manifest.json", sha256=meta["source_manifest_sha256"]))
    original = read(source)
    require(original.get("width") == 1280 and original.get("height") == 720 and original.get("fps") == [30, 1], "来源尺寸/帧率改变")
    require(len({r["path"] for r in original["frames"]}) == len(original["frames"]), "来源文件重复引用")
    require(original["clip_id"] == meta["clip_id"] and original["frame_count"] == meta["frame_count"], "来源不匹配")
    require(set(meta["source_evidence"]) == {"rights_evidence", "acquisition_evidence"}, "来源证据不完整")
    for key, record in meta["source_evidence"].items():
        checked_file(manifest.parent, record)
        require(record["sha256"] == original["provenance"][key]["sha256"], "来源证据改变")
    snapshot = copy.deepcopy(original)
    snapshot["provenance"].update(meta["source_evidence"])
    validate_provenance(snapshot, manifest.parent)
    rows = meta["frames"]
    validate_timeline(rows, meta["frame_count"], config["capture"]["pts_grid_tolerance_ns"])
    for size in ("native", "low"):
        require(len({r[size]["path"] for r in rows}) == len(rows), "配对文件重复引用")
    require(len(original["frames"]) == len(rows), "源帧数改变")
    for row, src in zip(rows, original["frames"]):
        require((row["sequence"], row["pts_ns"], row["native"]["sha256"]) ==
                (src["sequence"], src["pts_ns"], src["sha256"]), "不是同一批源帧/PTS")
        native = pixels(checked_file(manifest.parent, row["native"]), config["native_size"])
        low = pixels(checked_file(manifest.parent, row["low"]), config["low_size"])
        require(hashlib.sha256(native.tobytes()).hexdigest() == row["native_pixels_sha256"], "原图像素哈希改变")
        require(hashlib.sha256(low.tobytes()).hexdigest() == row["low_pixels_sha256"], "低清像素哈希改变")
        require(np.array_equal(low, cv2.resize(native, tuple(config["low_size"]), interpolation=cv2.INTER_AREA)),
                "低清图不是源帧精确等比例 INTER_AREA 降采样")
    return meta


def point(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(
        type(x) in (float, int) and math.isfinite(x) and 0 <= x <= 1 for x in value)


def validate_annotations(review: dict[str, Any], pair: dict[str, Any]) -> None:
    require(review.get("reviewed_before_predictions") is True and review.get("predictions_viewed") is False,
            "真值尚未在预测前确认")
    require(review.get("complete_annotation") is True, "必须标注完整片段，不能只挑选成功动作")
    require(review.get("clip_id") == pair["clip_id"] and review.get("frame_count") == pair["frame_count"], "标注视频不符")
    rules = review["geometry"]
    roi = rules["roi"]
    require(isinstance(roi, list) and len(roi) == 4 and point(roi[:2]) and point(roi[2:]) and
            roi[0] < roi[2] and roi[1] < roi[3], "ROI 必须是非退化归一化矩形")
    line = rules["line"]
    require(isinstance(line, list) and len(line) == 4 and point(line[:2]) and point(line[2:]) and
            line[:2] != line[2:], "警戒线必须是非退化归一化线段")
    require(rules["dwell_roi"] == roi and rules["dwell_seconds"] == 3, "本轮停留区域及 3 秒规则固定")
    coverage = review["coverage"]
    require(coverage.get("real_people") is True, "不能用空场景计分")
    for key in ("near_far", "occlusion"):
        require(coverage.get(key) in {"present", "limited"}, "须明确远近/遮挡覆盖边界")
        if coverage[key] == "limited":
            require(bool(coverage.get(key + "_limitation", "").strip()), "缺少场景限制说明")
    events = review["events"]
    require(isinstance(events, list) and {e["event_type"] for e in events} <= EVENTS, "未知事件类型")
    require(len({e["event_id"] for e in events}) == len(events), "真值 event_id 重复")
    for event in events:
        frame = event["frame_sequence"]
        require(integer(frame) and frame < pair["frame_count"], "真值帧越界")
        require(point(event["anchor"]), "真值锚点须归一化")
        require(bool(event.get("subject_id")) and bool(event.get("rule_id")), "须固定人物和规则 ID")
        require(event["rule_id"] == RULE_IDS[event["event_type"]], "规则 ID 不符合现有事件接口")
        if event["event_type"] == "dwell":
            start = event.get("residence_start_frame")
            require(integer(start) and frame - start >= 90, "停留真值必须有至少 3 秒的在区时间")
        if event["event_type"] == "line_crossing":
            require(event.get("direction") in {"negative_to_positive", "positive_to_negative"}, "穿线方向缺失")
        # 这些人工观测用于关键事件窗口定位，不使用模型预测构造真值。
        observations = event["anchor_observations"]
        require(isinstance(observations, list) and len(observations) >= 2, "每个关键事件至少两个原图人工锚点观测")
        require(len({item["frame_sequence"] for item in observations}) == len(observations), "人工锚点帧重复")
        for item in observations:
            require(integer(item["frame_sequence"]) and item["frame_sequence"] < pair["frame_count"] and
                    abs(item["frame_sequence"] - frame) <= 60 and point(item["anchor"]), "关键窗口锚点无效")
    intervals = review["negative_intervals"]
    require(isinstance(intervals, list) and intervals, "缺少不应报警区间")
    for item in intervals:
        require(integer(item["start_frame"]) and integer(item["end_frame"]) and
                item["start_frame"] <= item["end_frame"] < pair["frame_count"], "负例区间越界")
        require(isinstance(item["event_types"], list) and item["event_types"] and
                set(item["event_types"]) <= EVENTS, "负例事件范围无效")
        require(not any(e["event_type"] in item["event_types"] and item["start_frame"] <= e["frame_sequence"] <= item["end_frame"]
                        for e in events), "负例区间与真值冲突")


def freeze(selection: Path, output: Path) -> dict[str, Any]:
    config = load_recipe()
    data = read(selection)
    require(data.get("protocol_id") == config["protocol_id"], "选择清单协议不符")
    require(data.get("predictions_viewed") is False, "已查看预测，不能进行预测前冻结")
    require(data.get("review_confirmed") is True, "需完成素材/规则/真值审核")
    require(data.get("device") == dict(power_mode_id=1, clocks="preserve_original_DVFS_controls"), "本轮设备条件不符")
    require(1 <= len(data["clips"]) <= 3, "最多三段，冻结后不得追加")
    require(not output.exists(), "拒绝覆盖冻结目录")
    clips = []
    covered_events: set[str] = set()
    for item in data["clips"]:
        pair_file = checked_file(selection.parent, item["pairs"])
        pair = verify(pair_file)
        annotation = checked_file(selection.parent, item["annotation"])
        review = read(annotation)
        validate_annotations(review, pair)
        covered_events.update(event["event_type"] for event in review["events"])
        clips.append(dict(clip_id=pair["clip_id"], frames=pair["frame_count"],
                          pairs=item["pairs"], annotation=item["annotation"]))
    require(len({c["clip_id"] for c in clips}) == len(clips), "视频重复")
    require(covered_events == EVENTS, "全部素材合计必须覆盖三类真值")
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "selection.json", data)
    sealed = dict(schema_version=1, protocol_id=config["protocol_id"], recipe_sha256=digest(RECIPE),
        selection_sha256=digest(output / "selection.json"), clips=clips, thresholds=config["thresholds"],
        bytetrack=config["bytetrack"], event_semantics=config["event_semantics"], matching=config["matching"],
        models=config["models"], device=data["device"],
        jobs=[dict(clip_id=clip["clip_id"], **group, status="NOT_RUN") for clip in clips for group in config["groups"]],
        status="INPUTS_FROZEN_EXECUTION_NOT_AUTHORIZED", reference_root=str(selection.parent.resolve()),
        runner_status="PENDING_TRACE_AND_DEVICE_PREFLIGHT", score_status="NOT_RUN")
    write_new(output / "frozen.json", sealed)
    return sealed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("prepare", "verify", "freeze"):
        child = sub.add_parser(name)
        child.add_argument("--input", type=Path, required=True)
        if name != "verify":
            child.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        value = verify(args.input) if args.action == "verify" else globals()[args.action](args.input, args.output)
        print(json.dumps(dict(status=value["status"], clip_id=value.get("clip_id"),
                             frames=value.get("frame_count"), device_operation=False), ensure_ascii=False))
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, OSError, ImportError) as error:
        print("preparation=FAIL: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
