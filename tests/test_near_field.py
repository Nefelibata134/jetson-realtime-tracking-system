from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import prepare_near_field as subject
import near_field_replay
import source_resolution_replay


def manifest():
    recipe=subject.load_recipe(); clip=recipe["clips"][0]
    n=clip["end_frame_exclusive"]-clip["start_frame"]
    return dict(schema_version=1,kind="derived720_near_field_frames",protocol_id=subject.PROTOCOL,recipe_sha256=subject.digest(subject.RECIPE),
        width=1280,height=720,fps=[30,1],clip_id=clip["id"],source=recipe["source"],transform=recipe["transform"],
        timeline=recipe["timeline"],frame_count=n,frames=[dict(sequence=i,source_frame=clip["start_frame"]+i,
            pts_ns=i*1000000000//30,path=f"frames/{i:06d}.png",sha256="0"*64,source_bgr_sha256="1"*64,
            pixels_sha256="2"*64) for i in range(n)])


class FrameContractTests(unittest.TestCase):
    def setUp(self): self.value=manifest()
    def reject(self):
        with self.assertRaises(ValueError): subject.validate_frames(self.value)
    def test_integer_30hz_floor(self): subject.validate_frames(self.value)
    def test_original_capture_pts_never_claimed(self):
        self.assertFalse(self.value["source"]["native_720"])
        self.assertFalse(self.value["source"]["packet_pts_available"])
        self.assertIsNone(self.value["source"]["original_capture_integrity"])
    def test_missing_frame(self): self.value["frames"].pop();self.reject()
    def test_duplicate_source_frame(self): self.value["frames"][2]["source_frame"]-=1;self.reject()
    def test_reordered_source_frame(self): self.value["frames"][2]["source_frame"]+=1;self.reject()
    def test_duplicate_replay_sequence(self): self.value["frames"][2]["sequence"]-=1;self.reject()
    def test_pts_floor_cannot_change_one_ns(self): self.value["frames"][1]["pts_ns"]+=1;self.reject()
    def test_pts_offset_not_allowed(self):
        for r in self.value["frames"]: r["pts_ns"]+=1000000
        self.reject()
    def test_duplicate_path(self): self.value["frames"][1]["path"]=self.value["frames"][0]["path"];self.reject()
    def test_native720_label_not_allowed(self): self.value["kind"]="native720_unannotated_frames";self.reject()
    def test_source_provenance_not_changed(self): self.value["source"]["native_720"]=True;self.reject()
    def test_unknown_clip(self): self.value["clip_id"]="other";self.reject()
    def test_bad_pixel_hash(self): self.value["frames"][0]["source_bgr_sha256"]="";self.reject()
    def test_recipe_hash(self): self.value["recipe_sha256"]="0"*64;self.reject()
    def test_no_deduplication(self): self.value["transform"]["deduplicate"]=True;self.reject()


class RecipeTests(unittest.TestCase):
    def reject_config(self,config):
        with patch.object(subject,"read",return_value=config),self.assertRaises(ValueError): subject.load_recipe()
    def test_missing_threshold(self):
        c=subject.load_recipe();del c["thresholds"]["score"];self.reject_config(c)
    def test_tuned_parameters_not_inherited(self):
        c=subject.load_recipe();c["thresholds"]["track"]=.35;self.reject_config(c)
    def test_no_extra_group(self):
        c=subject.load_recipe();c["groups"].append(dict(id="other",source="derived720",model="tiny640"));self.reject_config(c)
    def test_no_stretch(self):
        c=subject.load_recipe();c["transform"]["pad_top"]=0;self.reject_config(c)
    def test_fixed_windows(self):
        c=subject.load_recipe();c["clips"][0]["start_frame"]+=1;self.reject_config(c)
    def test_no_power_change(self):
        c=subject.load_recipe();c["device"]["power_mode_id"]=2;self.reject_config(c)
    def test_no_warmup_exclusion(self):
        c=subject.load_recipe();c["timeline"]["warmup_frames"]=30;self.reject_config(c)
    def test_wrong_source_before_output_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/"wrong.avi";src.write_bytes(b"not the source")
            with self.assertRaises(ValueError): subject.prepare(src,root/"new")
            self.assertFalse((root/"new").exists())
    def test_existing_output_not_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/"fake.avi";src.write_bytes(b"unit-test")
            c=subject.load_recipe();c["source"].update(bytes=src.stat().st_size,sha256=hashlib.sha256(src.read_bytes()).hexdigest())
            output=root/"existing";output.mkdir();sentinel=output/"keep";sentinel.write_text("preserve")
            with patch.object(subject,"load_recipe",return_value=c),self.assertRaises(ValueError): subject.prepare(src,output)
            self.assertEqual(sentinel.read_text(),"preserve")


class GeometryTransformTests(unittest.TestCase):
    def test_same_scale_with_documented_padding(self):
        self.assertEqual(subject.map_point(0,0),(0,8/3))
        self.assertEqual(subject.map_point(1920,1072),(1280,2152/3))
        a,b=subject.map_point(300,500),subject.map_point(600,800)
        self.assertAlmostEqual(b[0]-a[0],b[1]-a[1])
    def test_exact_pad_and_area_pixels(self):
        import cv2
        import numpy as np
        yy,xx=np.indices((1072,1920))
        source=np.stack((xx%256,yy%256,(xx+yy)%256),axis=2).astype(np.uint8)
        expected=np.full((1080,1920,3),114,np.uint8);expected[4:1076]=source
        expected=cv2.resize(expected,(1280,720),interpolation=cv2.INTER_AREA)
        actual=subject.transform_bgr(source)
        self.assertEqual(actual.shape,(720,1280,3))
        self.assertTrue(np.array_equal(expected,actual))
    def test_wrong_shape_not_relabelled(self):
        import numpy as np
        with self.assertRaises(ValueError): subject.transform_bgr(np.zeros((288,384,3),np.uint8))


class FreezeAndReplayTests(unittest.TestCase):
    """合成文件只测冻结绑定和任务派发，不是素材审核或模型预测。"""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config=subject.load_recipe()
        self.selected=dict(protocol_id=subject.PROTOCOL,predictions_viewed=False,review_confirmed=True,
                           device=self.config["device"],clips=[])
        self.metas={}
        for clip in self.config["clips"]:
            meta=manifest();count=clip["end_frame_exclusive"]-clip["start_frame"]
            meta.update(clip_id=clip["id"],frame_count=count,frames=meta["frames"][:count])
            for i,row in enumerate(meta["frames"]):row["source_frame"]=clip["start_frame"]+i
            path=self.root/(clip["id"]+".json");subject.write_new(path,meta);self.metas[path]=meta
            geometry=dict(roi=[.37,.7,.7,.995],line=[.5,.7,.5,.995],dwell_roi=[.37,.7,.7,.995],dwell_seconds=3)
            events=[]
            for kind,frame in (("roi_intrusion",100),("dwell",200),("line_crossing",300)):
                events.append(dict(event_id=kind,subject_id="synthetic-person",rule_id=subject.common.RULE_IDS[kind],
                    event_type=kind,frame_sequence=frame,anchor=[.5,.8],residence_start_frame=110,
                    direction="negative_to_positive" if kind=="line_crossing" else "none",
                    anchor_observations=[dict(frame_sequence=frame+i,anchor=[.5,.8]) for i in (-1,1)]))
            annotation=dict(reviewed_before_predictions=True,predictions_viewed=False,complete_annotation=True,
                clip_id=clip["id"],frame_count=count,geometry=geometry,
                coverage=dict(real_people=True,near_far="limited",near_far_limitation="synthetic fixture",occlusion="present"),
                events=events,negative_intervals=[dict(start_frame=0,end_frame=50,event_types=list(subject.common.EVENTS))],
                timeline_basis=self.config["timeline"]["basis"],prepared_sha256=subject.digest(path),
                geometry_frozen_before_predictions=True,review_evidence=["synthetic-fixture-not-actual-review"])
            ann=self.root/(clip["id"]+"-annotation.json");subject.write_new(ann,annotation)
            self.selected["clips"].append(dict(prepared=dict(path=path.name,sha256=subject.digest(path)),
                annotation=dict(path=ann.name,sha256=subject.digest(ann))))
        self.selection=self.root/"selection-input.json";subject.write_new(self.selection,self.selected)
        self.output=self.root/"frozen"
        self.pixel_stub=patch.object(subject,"verify",side_effect=lambda file,**kwargs:subject.read(file))
        self.pixel_stub.start();self.addCleanup(self.pixel_stub.stop)

    def replace_selection(self): self.selection.write_text(json.dumps(self.selected),encoding="utf-8")
    def freeze(self):return subject.freeze(self.selection,self.output)
    def load(self):
        seal=self.output/"frozen.json"
        return source_resolution_replay.inputs(self.root,seal,subject.digest(seal))
    def test_freeze_and_relocatable_root(self):
        sealed=self.freeze();actual,clips=self.load()
        self.assertEqual(len(actual["jobs"]),6);self.assertEqual(len(clips),3)
        self.assertEqual(sealed["score_status"],"NOT_RUN")
    def test_prediction_seen_rejected(self):
        self.selected["predictions_viewed"]=True;self.replace_selection()
        with self.assertRaises(ValueError):self.freeze()
        self.assertFalse(self.output.exists())
    def test_incomplete_review_rejected(self):
        self.selected["review_confirmed"]=False;self.replace_selection()
        with self.assertRaises(ValueError):self.freeze()
    def test_clip_removed_rejected(self):
        self.selected["clips"].pop();self.replace_selection()
        with self.assertRaises(ValueError):self.freeze()
    def test_reordered_clips_rejected(self):
        self.selected["clips"].reverse();self.replace_selection()
        with self.assertRaises(ValueError):self.freeze()
    def test_changed_annotation_hash_rejected(self):
        path=self.root/self.selected["clips"][0]["annotation"]["path"]
        path.write_text("{}",encoding="utf-8")
        with self.assertRaises(ValueError):self.freeze()
    def test_wrong_timeline_rejected(self):
        path=self.root/self.selected["clips"][0]["annotation"]["path"]
        value=subject.read(path);value["timeline_basis"]="original_camera_pts"
        path.write_text(json.dumps(value),encoding="utf-8")
        self.selected["clips"][0]["annotation"]["sha256"]=subject.digest(path);self.replace_selection()
        with self.assertRaises(ValueError):self.freeze()
    def test_per_clip_rule_change_rejected(self):
        path=self.root/self.selected["clips"][1]["annotation"]["path"]
        value=subject.read(path);value["geometry"]["line"]=[.6,.7,.6,.995]
        path.write_text(json.dumps(value),encoding="utf-8")
        self.selected["clips"][1]["annotation"]["sha256"]=subject.digest(path);self.replace_selection()
        with self.assertRaises(ValueError):self.freeze()
    def test_refuse_reused_freeze_directory(self):
        self.freeze()
        with self.assertRaises(ValueError):self.freeze()
        self.load()
    def test_extra_frozen_job_rejected_even_with_new_seal_hash(self):
        sealed=self.freeze();sealed["jobs"].append(sealed["jobs"][0])
        (self.output/"frozen.json").write_text(json.dumps(sealed),encoding="utf-8")
        with self.assertRaises(ValueError):self.load()
    def test_changed_matching_rejected(self):
        sealed=self.freeze();sealed["matching"]["frame_tolerance"]=90
        (self.output/"frozen.json").write_text(json.dumps(sealed),encoding="utf-8")
        with self.assertRaises(ValueError):self.load()
    def test_job_uses_same_frame_bytes_for_both_models(self):
        self.freeze();sealed,clips=self.load();clip=next(iter(clips.values()));seal=self.output/"frozen.json"
        jobs=[source_resolution_replay.make_job(clip,g,sealed,self.root/(g["model"]+".plan"),self.root,seal,subject.digest(seal))
              for g in self.config["groups"]]
        self.assertEqual(jobs[0]["frames"],jobs[1]["frames"])
        self.assertEqual(jobs[0]["kind"],"near_field_job_v6")
        self.assertNotEqual(jobs[0]["engine_input_shape"],jobs[1]["engine_input_shape"])
        for job in jobs:source_resolution_replay.verify_job(job)
        jobs[0]["thresholds"]=dict(jobs[0]["thresholds"],track=.35)
        with self.assertRaises(ValueError):source_resolution_replay.verify_job(jobs[0])
    def test_original_v5_still_has_four_groups(self):
        self.assertEqual(len(source_resolution_replay.recipe_for("tiny-source-resolution-development-v5")["groups"]),4)
        self.assertEqual(len(source_resolution_replay.recipe_for(subject.PROTOCOL)["groups"]),2)
        with self.assertRaises(ValueError):source_resolution_replay.recipe_for("unknown")


@unittest.skipUnless(os.environ.get("EDGE_VISION_REPLAY_CHECK_BINARY"),"需显式提供主机回放检查程序")
class CppContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        frames=[]
        for i in range(3):
            path=self.root/(str(i)+".png");path.write_bytes(b"schema fixture only; no image inference")
            frames.append(dict(sequence=i,pts_ns=i*1000000000//30,path=str(path)))
        self.job=dict(schema_version=1,kind="near_field_job_v6",protocol_id=subject.PROTOCOL,
            thresholds=subject.load_recipe()["thresholds"],bytetrack=subject.load_recipe()["bytetrack"],
            source="derived720",model="tiny416",group_id="derived720_tiny416",width=1280,height=720,
            engine_input_shape=[1,3,416,416],timeline_basis=subject.load_recipe()["timeline"]["basis"],
            geometry=dict(roi=[.3,.5,.7,.99],line=[.5,.5,.5,.99],dwell_roi=[.3,.5,.7,.99],dwell_seconds=3),frames=frames)
    def run_check(self,success):
        path=self.root/"job.json";path.write_text(json.dumps(self.job),encoding="utf-8")
        result=subprocess.run([os.environ["EDGE_VISION_REPLAY_CHECK_BINARY"],"--validate-job",str(path)],capture_output=True,text=True)
        self.assertEqual(result.returncode==0,success,result.stdout+result.stderr)
    def test_v6_schema(self):self.run_check(True)
    def test_tiny640_schema(self):
        self.job.update(model="tiny640",group_id="derived720_tiny640",engine_input_shape=[1,3,640,640]);self.run_check(True)
    def test_v5_native_unchanged(self):
        self.job.update(kind="source_resolution_job_v5",protocol_id="tiny-source-resolution-development-v5",source="native",group_id="native_tiny416");self.run_check(True)
    def test_v5_low_unchanged(self):
        self.job.update(kind="source_resolution_job_v5",protocol_id="tiny-source-resolution-development-v5",source="low",group_id="low_tiny416",width=384,height=216);self.run_check(True)
    def test_protocol_schema_pair_mismatch(self):self.job["kind"]="source_resolution_job_v5";self.run_check(False)
    def test_cannot_call_derived_native(self):self.job.update(source="native",group_id="native_tiny416");self.run_check(False)
    def test_unknown_protocol(self):self.job["protocol_id"]="other";self.run_check(False)
    def test_omitted_threshold(self):del self.job["thresholds"]["score"];self.run_check(False)
    def test_changed_threshold(self):self.job["thresholds"]["track"]=.35;self.run_check(False)
    def test_derived_pts_exact(self):self.job["frames"][1]["pts_ns"]+=1;self.run_check(False)
    def test_frame_gap(self):self.job["frames"][1]["sequence"]+=1;self.run_check(False)
    def test_source_pts_claim(self):self.job["timeline_basis"]="original_pts";self.run_check(False)


if __name__=="__main__": unittest.main()
