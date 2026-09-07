"""v6 派生输入适配器；检测、跟踪、执行与计分复用 source_resolution_replay。"""
from pathlib import Path

import prepare_near_field as prep

common=prep.common
read,require,digest=prep.read,prep.require,prep.digest


def inputs(root: Path, sealed_path: Path, sealed_sha: str, *, check_pixels_bytes: bool=True):
    require(digest(sealed_path)==sealed_sha,"冻结清单哈希改变")
    sealed=read(sealed_path);recipe=prep.load_recipe()
    require(sealed["protocol_id"]==prep.PROTOCOL and sealed["recipe_sha256"]==digest(prep.RECIPE),"近景协议身份不符")
    require(sealed["status"]=="INPUTS_FROZEN_EXECUTION_NOT_AUTHORIZED","冻结状态不符")
    selection=read(common.checked_file(sealed_path.parent,dict(path="selection.json",sha256=sealed["selection_sha256"])))
    require(selection["protocol_id"]==prep.PROTOCOL and selection["predictions_viewed"] is False
            and selection["review_confirmed"] is True,"预测前审核不符")
    for key in ("thresholds","bytetrack","models","event_semantics","matching","device","timeline"):
        require(sealed[key]==recipe[key],"冻结字段改变："+key)
    require(selection["device"]==sealed["device"],"选片设备配方不符")
    require(len(sealed["clips"])==len(selection["clips"])==3,"固定片段缺失")
    result={};covered=set();geometry=None
    for clip,selected,expected in zip(sealed["clips"],selection["clips"],recipe["clips"]):
        require(clip==dict(clip_id=expected["id"],frames=expected["end_frame_exclusive"]-expected["start_frame"],**selected),
                "固定片段引用改变")
        file=common.checked_file(root,clip["prepared"])
        if check_pixels_bytes:
            meta=prep.verify(file,check_pixels=False)
        else:
            meta=read(file);prep.validate_frames(meta)
        require(meta["clip_id"]==expected["id"] and meta["frame_count"]==clip["frames"],"片段身份或长度不符")
        annotation=read(common.checked_file(root,clip["annotation"]))
        prep.validate_annotation(annotation,meta,digest(file))
        if geometry is None:geometry=annotation["geometry"]
        require(annotation["geometry"]==geometry,"同机位几何不一致")
        covered.update(e["event_type"] for e in annotation["events"])
        result[clip["clip_id"]]=dict(clip=clip,prepared=meta,prepared_file=file,annotation=annotation)
    require(covered==common.EVENTS,"三类事件参考不完整")
    require(sealed["jobs"]==[dict(clip_id=c,**g,status="NOT_RUN") for c in result for g in recipe["groups"]],"固定六次回放集合改变")
    return sealed,result


def make_job(clip: dict, group: dict, sealed: dict, engine: Path, root: Path, seal: Path, seal_sha: str):
    model=group["model"];meta=clip["prepared"];file=clip["prepared_file"]
    return dict(schema_version=1,kind="near_field_job_v6",protocol_id=sealed["protocol_id"],
        clip_id=meta["clip_id"],group_id=group["id"],source=group["source"],model=model,
        engine_path=str(engine.resolve()),engine_sha256=sealed["models"][model]["engine_sha256"],
        engine_input_shape=sealed["models"][model]["input_shape"],
        inputs_root=str(root.resolve()),frozen_path=str(seal.resolve()),frozen_sha256=seal_sha,
        prepared_sha256=digest(file),annotation_sha256=clip["clip"]["annotation"]["sha256"],
        width=1280,height=720,timeline_basis=sealed["timeline"]["basis"],
        geometry=clip["annotation"]["geometry"],thresholds=sealed["thresholds"],bytetrack=sealed["bytetrack"],
        frames=[dict(sequence=r["sequence"],source_frame=r["source_frame"],pts_ns=r["pts_ns"],
                     path=str((file.parent/r["path"]).resolve()),sha256=r["sha256"]) for r in meta["frames"]])
