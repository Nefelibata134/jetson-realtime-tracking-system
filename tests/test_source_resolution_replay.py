from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import source_resolution_replay as subject


def event(frame=1,kind="roi_intrusion",track_id=1):
    return dict(event_type=kind,rule_id=subject.prep.RULE_IDS[kind],track_id=track_id,class_id=0,
        frame_sequence=frame,pts_ns=frame*1000000000//30,anchor=dict(x=.5,y=.6),
        direction="negative_to_positive" if kind=="line_crossing" else "none")


def fixture():
    # 纯合成计分器单元输入；不是实机或数据集预测。
    frames=[dict(sequence=i,pts_ns=i*1000000000//30,path=f"{i}.png",sha256="0"*64) for i in range(4)]
    job=dict(clip_id="synthetic",group_id="native_tiny416",frames=frames,width=1280,height=720,
             geometry=dict(roi=[.2,.2,.8,.8],line=[.5,.2,.5,.8]))
    rows=[]
    for src in frames:
        t=dict(track_id=1,box=[600,332,80,100],class_id=0,confidence=.8,state="tracked",age=1,missed_frames=0,anchor=[.5,.6])
        rows.append(dict(sequence=src["sequence"],pts_ns=src["pts_ns"],stream_generation=0,
            detections=[dict(box=t["box"],class_id=0,confidence=.8)],tracks=[t],
            events=[event()] if src["sequence"]==1 else [],
            timing_ms={key:float(src["sequence"]+1) for key in ("load","preprocess","trt","postprocess","bytetrack","event_rules","sequential_processing")}))
    summary=dict(status="COMPLETE",backend="jetson_tensorrt",job=job,frames=4,target_reached=True,
        dropped_frames=0,sequence_gaps=0,warmup_frames=0,wall_seconds=2,replay_fps=2,
        media_evidence_status="NOT_PRODUCED_trace_only")
    truth=event();truth.update(event_id="truth",subject_id="p1",anchor=[.5,.6],annotation_uncertainty_frames=[0,2])
    return job,summary,rows,dict(events=[truth])


class ScoringTests(unittest.TestCase):
    def setUp(self): self.matching=subject.prep.load_recipe()["matching"]

    def test_empty_is_not_perfect(self):
        self.assertEqual(subject.counts(0,0,0),dict(tp=0,fp=0,fn=0,precision=None,recall=None,f1=None))

    def test_zero_detections_has_zero_recall(self):
        result=subject.score_events([event()],[],self.matching)["total"]
        self.assertIsNone(result["precision"]);self.assertEqual(result["recall"],0);self.assertEqual(result["f1"],0)

    def test_duplicate_prediction_is_fp(self):
        result=subject.score_events([event()],[event(),event(track_id=2)],self.matching)["total"]
        self.assertEqual((result["tp"],result["fp"],result["fn"]),(1,1,0))

    def test_matching_is_one_to_one(self):
        result=subject.score_events([event(),event()],[event()],self.matching)["total"]
        self.assertEqual((result["tp"],result["fp"],result["fn"]),(1,0,1))

    def test_opposite_line_direction_not_match(self):
        expected=event(kind="line_crossing");actual=copy.deepcopy(expected);actual["direction"]="positive_to_negative"
        self.assertEqual(subject.score_events([expected],[actual],self.matching)["total"]["tp"],0)

    def test_sixty_frame_gate_not_widened(self):
        self.assertEqual(subject.score_events([event(0)],[event(60)],self.matching)["total"]["tp"],1)
        self.assertEqual(subject.score_events([event(0)],[event(61)],self.matching)["total"]["tp"],0)

    def test_spatial_gate(self):
        actual=event();actual["anchor"]["x"]+=.21
        self.assertEqual(subject.score_events([event()],[actual],self.matching)["total"]["tp"],0)

    def test_other_event_type_does_not_match(self):
        self.assertEqual(subject.score_events([event()],[event(kind="dwell")],self.matching)["total"]["tp"],0)

    def test_unknown_rule_is_error_not_silent_exclusion(self):
        bad=event();bad["rule_id"]="other"
        with self.assertRaises(ValueError): subject.score_events([], [bad], self.matching)

    def test_nearest_rank_percentile(self):
        self.assertEqual(subject.p95(list(range(100))),94)
        with self.assertRaises(ValueError): subject.p95([1,math.nan])

    def test_geometry_sign_agrees_with_downward_vertical_line(self):
        geo=dict(roi=[.2,.2,.8,.8],line=[.5,.2,.5,.8])
        a=subject.geometry_distances([.4,.6],geo)
        self.assertAlmostEqual(a["line_signed_normalized_distance"],.1)
        self.assertAlmostEqual(a["roi_signed_normalized_distance"],.2)
        self.assertLess(subject.geometry_distances([.9,.6],geo)["roi_signed_normalized_distance"],0)


class TraceTests(unittest.TestCase):
    def setUp(self): self.job,self.summary,self.rows,self.annotation=fixture()
    def reject(self):
        with self.assertRaises(ValueError): subject.validate_trace(self.job,self.summary,self.rows)

    def test_complete_trace(self):
        self.assertEqual(len(subject.validate_trace(self.job,self.summary,self.rows)),1)

    def test_missing_frame(self): self.rows.pop();self.reject()
    def test_repeated_frame(self): self.rows[2]=copy.deepcopy(self.rows[1]);self.reject()
    def test_pts_changed(self): self.rows[1]["pts_ns"]+=1;self.reject()
    def test_bool_sequence(self): self.rows[1]["sequence"]=True;self.reject()
    def test_generation_reset(self): self.rows[2]["stream_generation"]=1;self.reject()
    def test_drop(self): self.summary["dropped_frames"]=1;self.reject()
    def test_gap(self): self.summary["sequence_gaps"]=1;self.reject()
    def test_target_not_reached(self): self.summary["target_reached"]=False;self.reject()
    def test_warmup_cannot_exclude_frames(self): self.summary["warmup_frames"]=1;self.reject()
    def test_incomplete_process(self): self.summary["status"]="RUNNING";self.reject()
    def test_host_backend_not_device(self): self.summary["backend"]="synthetic_host_check";self.reject()
    def test_changed_actual_job(self):
        self.summary["job"]=copy.deepcopy(self.job);self.summary["job"]["width"]=640;self.reject()
    def test_bad_bbox(self): self.rows[0]["tracks"][0]["box"][2]=0;self.reject()
    def test_nan_confidence(self): self.rows[0]["tracks"][0]["confidence"]=math.nan;self.reject()
    def test_wrong_anchor(self): self.rows[0]["tracks"][0]["anchor"][0]=.4;self.reject()
    def test_duplicate_track(self): self.rows[0]["tracks"].append(copy.deepcopy(self.rows[0]["tracks"][0]));self.reject()
    def test_event_has_no_track(self): self.rows[1]["events"][0]["track_id"]=2;self.reject()
    def test_event_pts_changed(self): self.rows[1]["events"][0]["pts_ns"]+=1;self.reject()
    def test_event_anchor_differs_from_track(self): self.rows[1]["events"][0]["anchor"]["x"]=.51;self.reject()
    def test_bad_stage_timing(self): self.rows[1]["timing_ms"]["trt"]=-1;self.reject()
    def test_throughput_mismatch(self): self.summary["replay_fps"]=30;self.reject()

    def test_evidence_missing_not_event_fn(self):
        result=subject.analyse(self.job,self.summary,self.rows,self.annotation,subject.prep.load_recipe()["matching"])
        self.assertEqual(result["quality"]["total"]["tp"],1)
        self.assertEqual(result["quality"]["total"]["fn"],0)
        self.assertIsNone(result["e2e_p95_ms"]);self.assertFalse(result["csi_acceptance"])
        self.assertEqual(result["person_detections"],4)

    def test_uncertainty_does_not_rewrite_primary_score(self):
        truth=self.annotation["events"][0];truth["frame_sequence"]=62;truth["annotation_uncertainty_frames"]=[60,63]
        result=subject.analyse(self.job,self.summary,self.rows,self.annotation,subject.prep.load_recipe()["matching"])
        self.assertEqual(result["quality"]["total"]["tp"],0)
        self.assertEqual(result["annotation_boundary_sensitivity"]["earliest_visual_boundary"]["tp"],1)
        self.assertEqual(truth["frame_sequence"],62)

    def test_matrix_cannot_summarise_partial_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"index.json"
            path.write_text(json.dumps(dict(inputs_root=folder,frozen_path="unused",frozen_sha256="0"*64,runs=[])),encoding="utf-8")
            with patch.object(subject,"inputs",return_value=({"protocol_id":subject.prep.load_recipe()["protocol_id"]}, {"a":{}})),self.assertRaises(ValueError):
                subject.score_matrix(path,Path(folder)/"score.json")
            self.assertFalse((Path(folder)/"score.json").exists())

    def test_v6_visual_boundary_changes_sensitivity_not_primary(self):
        truth=self.annotation["events"][0]
        del truth["annotation_uncertainty_frames"]
        truth.update(frame_sequence=62,visual_boundary_frames=[60,63])
        original=copy.deepcopy(self.annotation)
        result=subject.analyse(self.job,self.summary,self.rows,self.annotation,subject.prep.load_recipe()["matching"])
        self.assertEqual(result["quality"]["total"]["tp"],0)
        self.assertEqual(result["annotation_boundary_sensitivity"]["earliest_visual_boundary"]["tp"],1)
        self.assertEqual(result["annotation_boundary_sensitivity"]["latest_visual_boundary"]["tp"],0)
        self.assertEqual(self.annotation,original)

    def test_missing_time_band_uses_primary(self):
        self.assertEqual(subject.annotation_time_bounds(dict(frame_sequence=12)),[12,12])

    def test_conflicting_time_bands_rejected(self):
        with self.assertRaises(ValueError):
            subject.annotation_time_bounds(dict(frame_sequence=2,visual_boundary_frames=[1,3],annotation_uncertainty_frames=[0,4]))

    def test_invalid_time_bands_rejected(self):
        for bounds in ([3,1],[-1,3],[True,3],[1,2.5],[1],[0,1],"1,3"):
            with self.subTest(bounds=bounds),self.assertRaises(ValueError):
                subject.annotation_time_bounds(dict(frame_sequence=2,visual_boundary_frames=bounds))


if __name__=="__main__": unittest.main()
