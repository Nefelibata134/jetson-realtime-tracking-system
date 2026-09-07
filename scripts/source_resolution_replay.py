#!/usr/bin/env python3
"""冻结输入的顺序回放任务、完整帧门禁和事件计分；不控制服务或功率。"""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

import prepare_source_resolution as prep
from evaluate_caviar_events import match_events

require, read, digest, write_new = prep.require, prep.read, prep.digest, prep.write_new


def recipe_for(protocol_id: str):
    if protocol_id == "tiny-near-field-development-v6":
        import prepare_near_field
        return prepare_near_field.load_recipe()
    require(protocol_id == "tiny-source-resolution-development-v5", "未知回放协议")
    return prep.load_recipe()


def inputs(root: Path, sealed_path: Path, sealed_sha: str, *, check_pixels_bytes: bool = True):
    """板端只核对已冻结 PNG 字节，不用另一 OpenCV 版本重缩放。"""
    require(digest(sealed_path) == sealed_sha, "冻结清单哈希改变")
    sealed = read(sealed_path)
    if sealed["protocol_id"] == "tiny-near-field-development-v6":
        import near_field_replay
        return near_field_replay.inputs(root,sealed_path,sealed_sha,check_pixels_bytes=check_pixels_bytes)
    recipe = recipe_for(sealed["protocol_id"])
    require(sealed["recipe_sha256"] == digest(prep.RECIPE), "协议哈希改变")
    require(sealed["status"] == "INPUTS_FROZEN_EXECUTION_NOT_AUTHORIZED", "冻结状态不符")
    selection = read(prep.checked_file(sealed_path.parent, dict(path="selection.json",sha256=sealed["selection_sha256"])))
    require(selection["predictions_viewed"] is False and selection["review_confirmed"] is True, "预测前审核不符")
    require(sealed["device"] == dict(power_mode_id=1,clocks="preserve_original_DVFS_controls"), "设备条件改变")
    for key in ("thresholds","bytetrack","models","event_semantics","matching"):
        require(sealed[key] == recipe[key], "冻结字段改变："+key)
    require(1 <= len(sealed["clips"]) <= 3 and len(selection["clips"]) == len(sealed["clips"]), "选片数量改变")
    result = {}
    for clip, selected in zip(sealed["clips"],selection["clips"]):
        require(clip["pairs"] == selected["pairs"] and clip["annotation"] == selected["annotation"],"选片引用改变")
        pair_file = prep.checked_file(root,clip["pairs"])
        pair = read(pair_file)
        require(pair["recipe_sha256"] == sealed["recipe_sha256"] and pair["clip_id"] == clip["clip_id"],"配对不符")
        require(pair["frame_count"] == clip["frames"],"配对帧数改变")
        prep.validate_timeline(pair["frames"],clip["frames"],1000000)
        if check_pixels_bytes:
            for source in ("native","low"):
                require(len({r[source]["path"] for r in pair["frames"]}) == clip["frames"],"重复文件引用")
                for row in pair["frames"]: prep.checked_file(pair_file.parent,row[source])
            prep.checked_file(pair_file.parent,dict(path="source-evidence/native-manifest.json",sha256=pair["source_manifest_sha256"]))
            for record in pair["source_evidence"].values(): prep.checked_file(pair_file.parent,record)
        annotation = read(prep.checked_file(root,clip["annotation"]))
        prep.validate_annotations(annotation,pair)
        require(clip["clip_id"] not in result,"重复视频")
        result[clip["clip_id"]] = dict(clip=clip,pair=pair,pair_file=pair_file,annotation=annotation)
    expected = [dict(clip_id=c,**g,status="NOT_RUN") for c in result for g in recipe["groups"]]
    require(sealed["jobs"] == expected,"冻结任务集合改变")
    return sealed,result


def make_job(clip: dict, group: dict, sealed: dict, engine: Path, root: Path, seal: Path, seal_sha: str):
    if sealed["protocol_id"] == "tiny-near-field-development-v6":
        import near_field_replay
        return near_field_replay.make_job(clip,group,sealed,engine,root,seal,seal_sha)
    source, model = group["source"],group["model"]
    return dict(schema_version=1,kind="source_resolution_job_v5",protocol_id=sealed["protocol_id"],
        clip_id=clip["pair"]["clip_id"],group_id=group["id"],source=source,model=model,
        engine_path=str(engine.resolve()),engine_sha256=sealed["models"][model]["engine_sha256"],
        engine_input_shape=sealed["models"][model]["input_shape"],
        inputs_root=str(root.resolve()),frozen_path=str(seal.resolve()),frozen_sha256=seal_sha,
        pairs_sha256=digest(clip["pair_file"]),annotation_sha256=clip["clip"]["annotation"]["sha256"],
        width=1280 if source=="native" else 384,height=720 if source=="native" else 216,
        geometry=clip["annotation"]["geometry"],thresholds=sealed["thresholds"],bytetrack=sealed["bytetrack"],
        frames=[dict(sequence=r["sequence"],pts_ns=r["pts_ns"],
            path=str((clip["pair_file"].parent/r[source]["path"]).resolve()),sha256=r[source]["sha256"])
            for r in clip["pair"]["frames"]])


def verify_job(job: dict, *, check_pixels_bytes: bool = True):
    root, seal = Path(job["inputs_root"]),Path(job["frozen_path"])
    sealed, clips = inputs(root,seal,job["frozen_sha256"],check_pixels_bytes=check_pixels_bytes)
    group = next((g for g in recipe_for(sealed["protocol_id"])["groups"] if g["id"]==job["group_id"]),None)
    require(group is not None and job["clip_id"] in clips,"不是冻结任务")
    clip = clips[job["clip_id"]]
    expected = make_job(clip,group,sealed,Path(job["engine_path"]),root,seal,job["frozen_sha256"])
    require(expected==job,"任务字段改变或阈值未显式提供")
    return sealed,clip


def prepare_jobs(args):
    sealed,clips=inputs(args.inputs_root,args.frozen,args.frozen_sha256)
    engines=dict(tiny416=args.engine416,tiny640=args.engine640)
    for model,path in engines.items():
        require(path.is_file() and digest(path)==sealed["models"][model]["engine_sha256"],"候选 engine 哈希不符："+model)
    args.output.mkdir(parents=False,exist_ok=False)
    jobs=[]
    for clip in clips.values():
        for group in recipe_for(sealed["protocol_id"])["groups"]:
            job=make_job(clip,group,sealed,engines[group["model"]],args.inputs_root,args.frozen,args.frozen_sha256)
            path=args.output/(job["clip_id"]+"--"+job["group_id"]+".json")
            write_new(path,job);jobs.append(dict(path=path.name,sha256=digest(path),status="NOT_RUN"))
    write_new(args.output/"jobs.json",dict(frozen_sha256=args.frozen_sha256,jobs=jobs,service_operation=False))


def finite(value, *, nonnegative=True):
    return type(value) in (int,float) and math.isfinite(value) and (not nonnegative or value>=0)


def counts(tp,fp,fn):
    return dict(tp=tp,fp=fp,fn=fn,precision=tp/(tp+fp) if tp+fp else None,
        recall=tp/(tp+fn) if tp+fn else None,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None)


def score_events(expected, actual, matching):
    by_class={}
    for kind,rule in prep.RULE_IDS.items():
        truth=[copy.deepcopy(e) for e in expected if e["event_type"]==kind and e["rule_id"]==rule]
        prediction=[e for e in actual if e["event_type"]==kind and e["rule_id"]==rule]
        for e in truth:
            if isinstance(e["anchor"],list): e["anchor"]=dict(zip(("x","y"),e["anchor"]))
        matches,fn,fp=match_events(truth,prediction,frame_tolerance=matching["frame_tolerance"],
                                  anchor_tolerance=matching["anchor_distance_tolerance"])
        by_class[kind]=dict(**counts(len(matches),len(fp),len(fn)),matches=matches,
            false_negatives=[truth[i] for i in fn],false_positives=[prediction[i] for i in fp])
    # 不把未知规则的报警静默丢掉。
    require(all(e["event_type"] in prep.RULE_IDS and e["rule_id"]==prep.RULE_IDS[e["event_type"]] for e in actual),"未知事件/规则")
    total=counts(*(sum(x[k] for x in by_class.values()) for k in ("tp","fp","fn")))
    return dict(by_class=by_class,total=total)


def p95(values):
    require(values and all(finite(x) for x in values),"无效阶段耗时")
    return sorted(values)[math.ceil(.95*len(values))-1]


def geometry_distances(anchor, geometry):
    x,y=anchor
    x0,y0,x1,y1=geometry["line"]
    line=((x1-x0)*(y-y0)-(y1-y0)*(x-x0))/math.hypot(x1-x0,y1-y0)
    left,top,right,bottom=geometry["roi"]
    if left<=x<=right and top<=y<=bottom:
        roi=min(x-left,right-x,y-top,bottom-y)
    else:
        roi=-math.hypot(max(left-x,0,x-right),max(top-y,0,y-bottom))
    return dict(line_signed_normalized_distance=line,roi_signed_normalized_distance=roi)


def validate_trace(job, summary, rows):
    require(summary.get("status")=="COMPLETE" and summary.get("backend")=="jetson_tensorrt","非完整实机回放")
    require(summary.get("job")==job,"实际命令配置不符")
    require(summary.get("target_reached") is True and summary.get("frames")==len(job["frames"]),"未达到目标帧数")
    for key in ("dropped_frames","sequence_gaps","warmup_frames"):
        require(type(summary.get(key)) is int and summary[key]==0,"完整帧门禁："+key)
    require(len(rows)==len(job["frames"]),"trace 帧数不完整")
    actual=[]
    for row,src in zip(rows,job["frames"]):
        require(type(row.get("sequence")) is int and row["sequence"]==src["sequence"] and
                type(row.get("pts_ns")) is int and row["pts_ns"]==src["pts_ns"] and
                type(row.get("stream_generation")) is int and row["stream_generation"]==0,"trace 序号/PTS/代次不符")
        track_ids=set()
        for key in ("detections","tracks","events"):
            require(isinstance(row.get(key),list),"trace 列表缺失")
        for entity in row["detections"]+row["tracks"]:
            box=entity["box"]
            require(isinstance(box,list) and len(box)==4 and all(finite(x,nonnegative=False) for x in box)
                    and box[2]>0 and box[3]>0,"无效框")
            require(type(entity["class_id"]) is int and 0<=entity["class_id"]<80,"无效类别")
            require(finite(entity["confidence"]) and entity["confidence"]<=1,"无效置信度")
        for track in row["tracks"]:
            require(prep.integer(track["track_id"],1) and track["track_id"] not in track_ids,"无效/重复轨迹 ID")
            track_ids.add(track["track_id"])
            require(track["class_id"]==0 and track["state"]=="tracked" and track["missed_frames"]==0,"轨迹状态不符")
            x,y,w,h=track["box"]
            a=[min(1,max(0,(x+w/2)/job["width"])),min(1,max(0,(y+h)/job["height"]))]
            require(prep.point(track["anchor"]) and all(abs(u-v)<=1e-5 for u,v in zip(track["anchor"],a)),"底边锚点不符")
        for event in row["events"]:
            require(event["frame_sequence"]==row["sequence"] and event["pts_ns"]==row["pts_ns"],"事件 PTS/帧不符")
            require(event["track_id"] in track_ids and event["class_id"]==0,"事件缺少当前轨迹")
            require(event["event_type"] in prep.RULE_IDS and event["rule_id"]==prep.RULE_IDS[event["event_type"]],"事件规则不符")
            a=event["anchor"]
            require(isinstance(a,dict) and prep.point([a.get("x"),a.get("y")]),"事件锚点不符")
            track=next(t for t in row["tracks"] if t["track_id"]==event["track_id"])
            require(abs(a["x"]-track["anchor"][0])<=1e-5 and abs(a["y"]-track["anchor"][1])<=1e-5,
                    "事件锚点不是当前轨迹底边中心")
            require(event.get("direction") in ({"positive_to_negative","negative_to_positive"} if event["event_type"]=="line_crossing" else {"none"}),"事件方向不符")
            actual.append(event)
        for key in ("load","preprocess","trt","postprocess","bytetrack","event_rules","sequential_processing"):
            require(finite(row["timing_ms"][key]),"无效阶段耗时")
    require(finite(summary["wall_seconds"]) and summary["wall_seconds"]>0,"吞吐时间无效")
    require(finite(summary["replay_fps"]) and math.isclose(summary["replay_fps"],len(rows)/summary["wall_seconds"],rel_tol=1e-8),"吞吐计算不一致")
    return actual


def annotation_time_bounds(event):
    """读取已冻结的视觉时间带；兼容 v5 字段，不重写主参考时刻。"""
    legacy = event.get("annotation_uncertainty_frames")
    visual = event.get("visual_boundary_frames")
    require(legacy is None or visual is None or legacy == visual, "视觉时间带字段冲突")
    bounds = visual if visual is not None else legacy
    if bounds is None:
        bounds = [event["frame_sequence"]] * 2
    require(isinstance(bounds, list) and len(bounds) == 2
            and all(prep.integer(value) for value in bounds)
            and bounds[0] <= event["frame_sequence"] <= bounds[1], "视觉时间带无效")
    return bounds


def analyse(job,summary,rows,annotation,matching):
    actual=validate_trace(job,summary,rows)
    quality=score_events(annotation["events"],actual,matching)
    sensitivity={}
    for index,name in enumerate(("earliest_visual_boundary","latest_visual_boundary")):
        shifted=copy.deepcopy(annotation["events"])
        for e in shifted: e["frame_sequence"]=annotation_time_bounds(e)[index]
        sensitivity[name]=score_events(shifted,actual,matching)["total"]
    windows=[]
    for truth in annotation["events"]:
        candidates=[]
        for row in rows:
            if abs(row["sequence"]-truth["frame_sequence"])>60: continue
            for track in row["tracks"]:
                if math.dist(track["anchor"],truth["anchor"])<=.2:
                    candidates.append(dict(sequence=row["sequence"],pts_ns=row["pts_ns"],track_id=track["track_id"],anchor=track["anchor"],box=track["box"],
                        **geometry_distances(track["anchor"],job["geometry"])))
        windows.append(dict(event_id=truth["event_id"],candidate_observations=candidates,
            identity_assignment="spatial_candidates_not_verified_GT_identity"))
    return dict(status="DEVELOPMENT_NOT_GATED",clip_id=job["clip_id"],group_id=job["group_id"],
        quality=quality,annotation_boundary_sensitivity=sensitivity,window_diagnostics=windows,
        person_detections=sum(sum(d["class_id"]==0 for d in r["detections"]) for r in rows),
        tracked_frames=sum(bool(r["tracks"]) for r in rows),track_observations=sum(len(r["tracks"]) for r in rows),
        timing_p95_ms={key:p95([r["timing_ms"][key] for r in rows]) for key in rows[0]["timing_ms"]},
        timing_percentile_method="nearest_rank_all_frames_including_cold_start_no_scored_warmup",
        replay_fps=summary["replay_fps"],e2e_p95_ms=None,event_io_ms=None,
        media_evidence_status=summary["media_evidence_status"],media_missing_is_not_event_FN=True,
        csi_acceptance=False)


def run_job(args):
    require(platform.system()=="Linux" and platform.machine()=="aarch64","真实回放只在目标 Jetson 执行")
    job=read(args.job);verify_job(job)
    require(digest(Path(job["engine_path"]))==job["engine_sha256"],"engine 哈希不符")
    power=subprocess.run(["nvpmodel","-q"],text=True,capture_output=True,check=True).stdout
    require("25W" in power and power.strip().splitlines()[-1].strip()=="1","不是冻结的25W模式")
    active=subprocess.run(["systemctl","is-active","edge-vision.service"],text=True,capture_output=True)
    require(active.stdout.strip()=="inactive","必须在已授权停服和恢复保护窗口内执行")
    require(1<=args.timeout_seconds<=1500,"单次超时范围不符")
    args.output.mkdir(parents=False,exist_ok=False)
    command=[str(args.binary.resolve()),"--job",str(args.job.resolve()),"--output",str((args.output/"runtime").resolve())]
    receipt=dict(command=command,job_sha256=digest(args.job),binary_sha256=digest(args.binary),engine_sha256=job["engine_sha256"],power=power)
    write_new(args.output/"command.json",receipt)
    code=None
    try:
        with (args.output/"process.log").open("xb") as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=args.timeout_seconds,check=False)
            code=result.returncode
        require(code==0,"回放退出码非零")
        require(digest(args.job)==receipt["job_sha256"] and digest(args.binary)==receipt["binary_sha256"],"执行期间任务/程序改变")
        require(digest(Path(job["engine_path"]))==job["engine_sha256"],"执行期间engine改变")
        verify_job(job)
        summary=read(args.output/"runtime/summary.json")
        rows=[json.loads(line) for line in (args.output/"runtime/trace.jsonl").read_text(encoding="utf-8").splitlines()]
        validate_trace(job,summary,rows)
        write_new(args.output/"execution.json",dict(status="VALID_REPLAY_NOT_SCORED",exit_code=code,
            job_sha256=receipt["job_sha256"],trace_sha256=digest(args.output/"runtime/trace.jsonl"),summary_sha256=digest(args.output/"runtime/summary.json")))
    except BaseException as error:
        write_new(args.output/"execution.json",dict(status="NOT_SCORED",exit_code=code,error=str(error),error_type=type(error).__name__,automatic_retry=False))
        raise


def score_matrix(index_path: Path, output: Path):
    index=read(index_path)
    sealed,clips=inputs(Path(index["inputs_root"]),Path(index["frozen_path"]),index["frozen_sha256"])
    groups=recipe_for(sealed["protocol_id"])["groups"]
    expected={(c,g["id"]) for c in clips for g in groups}
    reports=[];seen=set()
    for record in index["runs"]:
        folder=Path(record["path"])
        execution=read(prep.checked_file(folder,dict(path="execution.json",sha256=record["execution_sha256"])))
        require(execution["status"]=="VALID_REPLAY_NOT_SCORED" and execution["exit_code"]==0,"无效回放不能计分")
        summary=read(prep.checked_file(folder,dict(path="runtime/summary.json",sha256=execution["summary_sha256"])))
        trace=prep.checked_file(folder,dict(path="runtime/trace.jsonl",sha256=execution["trace_sha256"]))
        job=summary["job"];verify_job(job,check_pixels_bytes=False)
        require(job["frozen_sha256"]==index["frozen_sha256"],"混合冻结轮次")
        key=(job["clip_id"],job["group_id"])
        require(key in expected and key not in seen,"重复/额外任务")
        seen.add(key)
        rows=[json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
        reports.append(analyse(job,summary,rows,clips[job["clip_id"]]["annotation"],sealed["matching"]))
    require(seen==expected,"不完整的冻结矩阵；未完成任务保持NOT_RUN")
    aggregate={}
    for group in groups:
        selected=[r for r in reports if r["group_id"]==group["id"]]
        classes={kind:counts(*(sum(r["quality"]["by_class"][kind][k] for r in selected) for k in ("tp","fp","fn"))) for kind in prep.RULE_IDS}
        aggregate[group["id"]]=dict(by_class=classes,total=counts(*(sum(c[k] for c in classes.values()) for k in ("tp","fp","fn"))))
    write_new(output,dict(status="DEVELOPMENT_NOT_GATED",frozen_sha256=index["frozen_sha256"],
        reports=reports,aggregate=aggregate,default_change=False,independent_holdout=False,csi_acceptance=False))


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest="action",required=True)
    prepare=sub.add_parser("prepare-jobs")
    for key in ("inputs-root","frozen","engine416","engine640","output"): prepare.add_argument("--"+key,type=Path,required=True)
    prepare.add_argument("--frozen-sha256",required=True)
    run=sub.add_parser("run")
    for key in ("job","binary","output"): run.add_argument("--"+key,type=Path,required=True)
    run.add_argument("--timeout-seconds",type=int,required=True)
    score=sub.add_parser("score")
    score.add_argument("--index",type=Path,required=True);score.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    try:
        if args.action=="prepare-jobs": prepare_jobs(args)
        elif args.action=="run": run_job(args)
        else: score_matrix(args.index,args.output)
    except (ValueError,KeyError,TypeError,OSError,StopIteration,subprocess.SubprocessError) as error:
        print("source_resolution=FAIL "+str(error),file=sys.stderr);return 1
    print("source_resolution=PASS action="+args.action);return 0


if __name__=="__main__": raise SystemExit(main())
