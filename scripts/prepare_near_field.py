#!/usr/bin/env python3
"""固定近景开发素材的派生720p、原图标注及冻结；不运行检测器或设备命令。"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
from typing import Any

import prepare_source_resolution as common

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "configs/benchmarks/tiny_near_field_v6.json"
PROTOCOL = "tiny-near-field-development-v6"
read, require, digest, write_new = common.read, common.require, common.digest, common.write_new


def load_recipe() -> dict[str, Any]:
    config = read(RECIPE)
    require(config["protocol_id"] == PROTOCOL, "近景协议不符")
    require(config["source"]["native_720"] is False and config["source"]["packet_pts_available"] is False,
            "不能将派生输入标为原生720p或原始PTS")
    require(config["source"]["size"] == [1920, 1072] and config["source"]["fps"] == [30, 1], "源尺寸/帧率改变")
    require(config["thresholds"] == dict(score=.1, nms=.45, track=.3, new_track=.4, match=.8), "五个阈值改变")
    require(config["bytetrack"] == dict(frame_rate=30, buffer=30, second_match=.5, unconfirmed_match=.7), "ByteTrack设置改变")
    require(config["groups"] == [dict(id="derived720_"+m, source="derived720", model=m) for m in ("tiny416", "tiny640")], "只允许同输入固定两组")
    t = config["transform"]
    require(t == dict(source_pixel_format="BGR8", pad_top=4, pad_bottom=4, pad_left=0, pad_right=0,
                     pad_bgr=[114,114,114], padded_size=[1920,1080], output_size=[1280,720], scale=[2,3],
                     interpolation="OpenCV_INTER_AREA", codec="PNG", png_compression=1, crop=False,
                     lossy_reencode=False, frame_decimation=False, frame_interpolation=False, deduplicate=False), "变换设置改变")
    require(config["device"] == dict(power_mode_id=1, clocks="preserve_original_DVFS_controls"), "设备配方改变")
    windows = [(c["start_frame"], c["end_frame_exclusive"]) for c in config["clips"]]
    require(windows == [(3750,4650),(4950,5850),(8100,8850)], "首轮窗口改变")
    require(len({c["id"] for c in config["clips"]}) == 3, "片段ID重复")
    require(config["timeline"]["warmup_frames"] == 0 and config["timeline"]["preserve_every_selected_decoded_frame"] is True,
            "禁止排除已选帧")
    return config


def transform_bgr(frame):
    import cv2
    import numpy as np
    require(frame.shape == (1072,1920,3) and frame.dtype == np.uint8, "源帧不是1920x1072 BGR8")
    # 先补至严格16:9，再以相同的横纵缩放比例生成720p；没有裁切或拉伸。
    padded = cv2.copyMakeBorder(frame,4,4,0,0,cv2.BORDER_CONSTANT,value=(114,114,114))
    return cv2.resize(padded,(1280,720),interpolation=cv2.INTER_AREA)


def map_point(x: float, y: float) -> tuple[float,float]:
    """源图连续几何坐标到派生720p坐标；像素中心采样规则由OpenCV负责。"""
    return x*2/3, (y+4)*2/3


def validate_frames(meta: dict[str, Any]) -> None:
    config = load_recipe()
    require(meta["schema_version"] == 1 and meta["kind"] == "derived720_near_field_frames" and meta["protocol_id"] == PROTOCOL, "派生输入schema不符")
    require(meta["recipe_sha256"] == digest(RECIPE), "配方哈希改变")
    require(meta["width"] == 1280 and meta["height"] == 720 and meta["fps"] == [30,1], "派生尺寸/帧率改变")
    require(meta["source"] == config["source"] and meta["transform"] == config["transform"] and meta["timeline"] == config["timeline"], "来源/变换/时钟改变")
    clip = next((c for c in config["clips"] if c["id"] == meta["clip_id"]),None)
    require(clip is not None, "不是固定片段")
    rows = meta["frames"]
    require(meta["frame_count"] == clip["end_frame_exclusive"]-clip["start_frame"], "窗口帧数改变")
    common.validate_timeline(rows,meta["frame_count"],1)
    # 30Hz整数纳秒不能逐帧精确表示；显式使用floor，误差小于1ns。
    for i,row in enumerate(rows):
        require(row["source_frame"] == clip["start_frame"]+i, "源帧跳过/重复/重排")
        require(type(row["source_frame"]) is int and row["pts_ns"] == i*1000000000//30, "派生PTS或源帧类型不符")
        for key in ("sha256","source_bgr_sha256","pixels_sha256"):
            require(isinstance(row[key],str) and common.SHA.fullmatch(row[key]), "像素/文件哈希缺失")
    require(len({r["path"] for r in rows}) == len(rows), "帧文件重复引用")


def prepare(source: Path, output: Path) -> dict[str, Any]:
    import cv2
    import numpy as np
    config = load_recipe()
    require(source.is_file() and source.stat().st_size == config["source"]["bytes"] and digest(source) == config["source"]["sha256"], "源AVI身份不符")
    require(not output.exists(), "拒绝复用准备目录")
    output.mkdir(parents=True,exist_ok=False)
    recipe_hash = digest(RECIPE)
    write_new(output/"recipe.snapshot.json",config)
    buffers = {c["id"]: [] for c in config["clips"]}
    for clip in config["clips"]:
        (output/clip["id"]/"frames").mkdir(parents=True,exist_ok=False)
    cap = cv2.VideoCapture(str(source))
    total, stored = 0, 0
    try:
        require(cap.isOpened(), "源视频无法打开")
        require(abs(cap.get(cv2.CAP_PROP_FPS)-30) < 1e-6, "解码声明帧率不符")
        require(round(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == config["source"]["decoded_frames"], "源帧数声明不符")
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            require(round(cap.get(cv2.CAP_PROP_POS_FRAMES)) == total+1, "解码序号不连续")
            require(frame.shape == (1072,1920,3) and frame.dtype == np.uint8, "源帧契约改变")
            for clip in config["clips"]:
                if clip["start_frame"] <= total < clip["end_frame_exclusive"]:
                    i = total-clip["start_frame"]
                    derived = transform_bgr(frame)
                    file = output/clip["id"]/"frames"/f"{i:06d}.png"
                    require(not file.exists(), "拒绝覆盖帧")
                    require(cv2.imwrite(str(file),derived,[cv2.IMWRITE_PNG_COMPRESSION,1]), "PNG写入失败")
                    require(np.array_equal(derived,cv2.imread(str(file),cv2.IMREAD_UNCHANGED)), "PNG像素回读不一致")
                    buffers[clip["id"]].append(dict(sequence=i,source_frame=total,pts_ns=i*1000000000//30,
                        path="frames/"+file.name,sha256=digest(file),source_bgr_sha256=hashlib.sha256(frame.tobytes()).hexdigest(),
                        pixels_sha256=hashlib.sha256(derived.tobytes()).hexdigest()))
                    stored += 1
            total += 1
            if total % 900 == 0: print(f"decoded={total} stored={stored}",flush=True)
        require(total == config["source"]["decoded_frames"], "解码提前结束或额外帧")
        require(digest(source) == config["source"]["sha256"] and digest(RECIPE) == recipe_hash, "处理期间源文件或配方改变")
        receipts = []
        for clip in config["clips"]:
            meta = dict(schema_version=1,kind="derived720_near_field_frames",protocol_id=PROTOCOL,
                recipe_sha256=recipe_hash,clip_id=clip["id"],width=1280,height=720,fps=[30,1],
                source=config["source"],transform=config["transform"],timeline=config["timeline"],
                frame_count=len(buffers[clip["id"]]),frames=buffers[clip["id"]],
                decoder=dict(opencv=cv2.__version__,numpy=np.__version__,backend=cap.getBackendName()),
                status="FRAMES_PREPARED_ANNOTATIONS_PENDING")
            validate_frames(meta)
            file=output/clip["id"]/"frames.json";write_new(file,meta)
            receipts.append(dict(clip_id=clip["id"],path=file.relative_to(output).as_posix(),sha256=digest(file),frames=meta["frame_count"]))
        result=dict(status="PREPARED_NOT_FROZEN",protocol_id=PROTOCOL,recipe_sha256=recipe_hash,
                    source_sha256=config["source"]["sha256"],source_decoded_frames=total,selected_frames=stored,
                    clips=receipts,predictions_viewed=False,device_operation=False)
        write_new(output/"prepared.json",result)
        return result
    except BaseException as error:
        write_new(output/"preparation-failure.json",dict(error=str(error),type=type(error).__name__,decoded_frames=total,stored_frames=stored,automatic_retry=False))
        raise
    finally:
        cap.release()


def verify(manifest: Path, *, check_pixels: bool = True):
    meta=read(manifest);validate_frames(meta)
    for row in meta["frames"]:
        path=common.checked_file(manifest.parent,row)
        if check_pixels:
            frame=common.pixels(path,[1280,720])
            require(hashlib.sha256(frame.tobytes()).hexdigest()==row["pixels_sha256"], "派生像素改变")
    return meta


def validate_annotation(annotation: dict, meta: dict, prepared_sha: str):
    config=load_recipe()
    common.validate_annotations(annotation,meta)
    require(annotation.get("timeline_basis")==config["timeline"]["basis"],"标注时间轴不符")
    require(annotation.get("prepared_sha256")==prepared_sha,"标注不属于此派生输入")
    require(annotation.get("geometry_frozen_before_predictions") is True,"几何未固定")
    require(bool(annotation.get("review_evidence")),"缺少原图审核范围")


def freeze(selection: Path, output: Path):
    require(not output.exists(),"拒绝覆盖冻结目录")
    config=load_recipe(); data=read(selection)
    require(data["protocol_id"]==PROTOCOL and data["predictions_viewed"] is False and data["review_confirmed"] is True,"不是预测前完整审核")
    require(data["device"]==config["device"],"设备配方改变")
    require(len(data["clips"])==len(config["clips"]),"固定片段缺失")
    clips=[]; covered=set(); geometry=None
    for selected, expected in zip(data["clips"],config["clips"]):
        file=common.checked_file(selection.parent,selected["prepared"]);meta=verify(file)
        require(meta["clip_id"]==expected["id"],"固定片段顺序改变")
        annotation=read(common.checked_file(selection.parent,selected["annotation"]))
        validate_annotation(annotation,meta,digest(file))
        if geometry is None: geometry=annotation["geometry"]
        require(annotation["geometry"]==geometry,"同机位三段必须共用几何")
        covered.update(e["event_type"] for e in annotation["events"])
        clips.append(dict(clip_id=meta["clip_id"],frames=meta["frame_count"],**selected))
    require(covered==common.EVENTS,"三类事件参考未覆盖")
    output.mkdir(parents=True,exist_ok=False)
    write_new(output/"selection.json",data)
    sealed=dict(schema_version=1,protocol_id=PROTOCOL,recipe_sha256=digest(RECIPE),selection_sha256=digest(output/"selection.json"),
        clips=clips,**{k:config[k] for k in ("thresholds","bytetrack","models","event_semantics","matching","device","timeline")},
        jobs=[dict(clip_id=c["clip_id"],**g,status="NOT_RUN") for c in clips for g in config["groups"]],
        status="INPUTS_FROZEN_EXECUTION_NOT_AUTHORIZED",reference_root=str(selection.parent.resolve()),
        score_status="NOT_RUN",independent_holdout=False,csi_acceptance=False)
    write_new(output/"frozen.json",sealed)
    return sealed


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("prepare","verify","freeze"))
    p.add_argument("--input",type=Path,required=True);p.add_argument("--output",type=Path)
    args=p.parse_args()
    try:
        require(args.action=="verify" or args.output is not None,"缺少新输出目录")
        result=verify(args.input) if args.action=="verify" else globals()[args.action](args.input,args.output)
        print("near_field=PASS status="+result["status"])
    except (ValueError,KeyError,TypeError,OSError,ImportError,AttributeError) as error:
        print("near_field=FAIL "+str(error),file=sys.stderr);return 1
    return 0


if __name__=="__main__": raise SystemExit(main())
