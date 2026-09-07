from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import shutil
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_source_resolution as subject


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(sequence=i, pts_ns=7000000000 + i * 1000000000 // 30) for i in range(6)]

    def test_30fps_integer_pts(self):
        subject.validate_timeline(self.rows, 6, 1000000)

    def test_missing_frame(self):
        with self.assertRaises(ValueError):
            subject.validate_timeline(self.rows[:-1], 6, 1000000)

    def test_duplicate_sequence(self):
        self.rows[3]["sequence"] = 2
        with self.assertRaises(ValueError):
            subject.validate_timeline(self.rows, 6, 1000000)

    def test_duplicate_pts(self):
        self.rows[3]["pts_ns"] = self.rows[2]["pts_ns"]
        with self.assertRaises(ValueError):
            subject.validate_timeline(self.rows, 6, 1000000)

    def test_missing_delivery_interval(self):
        for row in self.rows[3:]:
            row["pts_ns"] += 33333333
        with self.assertRaises(ValueError):
            subject.validate_timeline(self.rows, 6, 1000000)

    def test_no_tolerance_widening(self):
        with self.assertRaises(ValueError):
            subject.validate_timeline(self.rows, 6, 34000000)

    def test_noninteger_sequence(self):
        self.rows[0]["sequence"] = False
        with self.assertRaises(ValueError):
            subject.validate_timeline(self.rows, 6, 1000000)

    def test_fixed_thresholds(self):
        recipe = subject.load_recipe()
        recipe["thresholds"]["track"] = .35
        with patch.object(subject, "read", return_value=recipe), self.assertRaises(ValueError):
            subject.load_recipe()

    def test_no_additional_group(self):
        recipe = subject.load_recipe()
        recipe["groups"].append(dict(id="tuned", source="native", model="tiny640"))
        with patch.object(subject, "read", return_value=recipe), self.assertRaises(ValueError):
            subject.load_recipe()


def annotation(frames=96):
    events = []
    for i, kind in enumerate(sorted(subject.EVENTS)):
        frame = 94 if kind == "dwell" else 2+i
        events.append(dict(event_id=f"e{i}", event_type=kind, rule_id=subject.RULE_IDS[kind], subject_id="p1",
            frame_sequence=frame, residence_start_frame=4 if kind == "dwell" else None,
            anchor=[.5, .6], direction="negative_to_positive" if kind == "line_crossing" else "none",
            anchor_observations=[dict(frame_sequence=frame-1, anchor=[.4,.6]), dict(frame_sequence=frame+1, anchor=[.6,.6])]))
    return dict(clip_id="synthetic_checks_only", frame_count=frames, reviewed_before_predictions=True,
        predictions_viewed=False, complete_annotation=True,
        geometry=dict(roi=[.2,.2,.8,.8], dwell_roi=[.2,.2,.8,.8], line=[.5,.1,.5,.9], dwell_seconds=3),
        coverage=dict(real_people=True, near_far="limited", near_far_limitation="仅用于结构测试",
                      occlusion="limited", occlusion_limitation="仅用于结构测试"),
        events=events, negative_intervals=[dict(start_frame=0, end_frame=0, event_types=sorted(subject.EVENTS))])


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.value = annotation()
        self.pair = dict(clip_id="synthetic_checks_only", frame_count=96)

    def test_valid_schema_not_actual_quality(self):
        subject.validate_annotations(self.value, self.pair)

    def test_reject_review_after_prediction(self):
        self.value["predictions_viewed"] = True
        with self.assertRaises(ValueError):
            subject.validate_annotations(self.value, self.pair)

    def test_no_empty_scene(self):
        self.value["coverage"]["real_people"] = False
        with self.assertRaises(ValueError):
            subject.validate_annotations(self.value, self.pair)

    def test_no_dwell_change(self):
        self.value["geometry"]["dwell_seconds"] = 5
        with self.assertRaises(ValueError):
            subject.validate_annotations(self.value, self.pair)

    def test_geometry_outside_frame(self):
        self.value["geometry"]["line"][0] = -0.1
        with self.assertRaises(ValueError):
            subject.validate_annotations(self.value, self.pair)

    def test_negative_conflicts_with_truth(self):
        self.value["negative_intervals"][0]["end_frame"] = 5
        with self.assertRaises(ValueError):
            subject.validate_annotations(self.value, self.pair)

    def test_anchor_diagnostics_required(self):
        self.value["events"][0]["anchor_observations"] = []
        with self.assertRaises(ValueError):
            subject.validate_annotations(self.value, self.pair)

    def test_dwell_too_short(self):
        self.value["events"][0]["residence_start_frame"] = 60
        with self.assertRaises(ValueError):
            subject.validate_annotations(self.value, self.pair)

    def test_wrong_rule_id(self):
        self.value["events"][0]["rule_id"] = "unknown"
        with self.assertRaises(ValueError):
            subject.validate_annotations(self.value, self.pair)


class PixelPairTests(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        # 合成图案只验证变换和门禁，不能充当含行人质量证据。
        self.rows = []
        yy, xx = np.indices((720, 1280))
        for i in range(6):
            frame = np.stack(((xx+i)%256, (yy+2*i)%256, (xx+yy)%256), axis=2).astype(np.uint8)
            name = f"{i:06d}.png"
            self.assertTrue(cv2.imwrite(str(self.source / name), frame))
            self.rows.append(dict(sequence=i, pts_ns=i*1000000000//30, path=name, sha256=subject.digest(self.source/name)))
        subject.write_new(self.source / "rights.json", dict(synthetic_unit_test=True))
        evidence = dict(path="rights.json", sha256=subject.digest(self.source / "rights.json"))
        self.meta = dict(schema_version=1, kind="native720_unannotated_frames", clip_id="synthetic_checks_only",
            width=1280, height=720, fps=[30,1], pixel_format="BGR8", codec="PNG", frame_count=6, frames=self.rows,
            provenance=dict(kind="authorized_native_video", rights_confirmed=True, native_720_confirmed=True,
                unannotated=True, not_upscaled=True, not_holdout=True, reviewed_before_predictions=True,
                source_description="确定性合成单元测试，不是场景质量证据", rights_evidence=evidence, acquisition_evidence=evidence),
            acquisition=dict(target_reached=True, unexpected_dropped_frames=0, sequence_gaps=0, decode_errors=0,
                             warmup_discarded_frames=0, planned_decimated_frames=0))
        self.input = self.source / "native.json"
        subject.write_new(self.input, self.meta)
        self.output = self.root / "pair"

    def prepare(self):
        return subject.prepare(self.input, self.output)

    def test_exact_png_pair_and_pts(self):
        value = self.prepare()
        verified = subject.verify(self.output / "pairs.json")
        self.assertEqual(value, verified)
        self.assertEqual([r["pts_ns"] for r in value["frames"]], [r["pts_ns"] for r in self.rows])
        self.assertEqual(value["frame_count"], 6)

    def test_output_never_reused(self):
        self.prepare()
        with self.assertRaises(ValueError):
            self.prepare()

    def test_hash_failure_before_output(self):
        (self.source / "000002.png").write_bytes(b"invalid")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_low_pixels_tampered_even_with_updated_file_hash(self):
        import cv2
        value = self.prepare()
        low_path = self.output / value["frames"][0]["low"]["path"]
        low = cv2.imread(str(low_path))
        low[0,0] = 0
        cv2.imwrite(str(low_path), low)
        value["frames"][0]["low"]["sha256"] = subject.digest(low_path)
        (self.output / "pairs.json").write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ValueError):
            subject.verify(self.output / "pairs.json")

    def test_wrong_source_resolution(self):
        value = copy.deepcopy(self.meta)
        value["height"] = 288
        self.input.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.prepare()

    def test_unconfirmed_native_provenance(self):
        value = copy.deepcopy(self.meta)
        value["provenance"]["native_720_confirmed"] = False
        self.input.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.prepare()

    def test_recorded_drop_fails(self):
        value = copy.deepcopy(self.meta)
        value["acquisition"]["unexpected_dropped_frames"] = 1
        self.input.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.prepare()

    def test_path_traversal(self):
        with self.assertRaises(ValueError):
            subject.safe_file(self.source, "../outside.png")

    def test_freeze_four_jobs_no_execution(self):
        for i in range(6, 96):
            name = f"{i:06d}.png"
            shutil.copyfile(self.source / "000000.png", self.source / name)
            self.rows.append(dict(sequence=i, pts_ns=i*1000000000//30, path=name, sha256=subject.digest(self.source/name)))
        self.meta["frame_count"] = 96
        self.input.write_text(json.dumps(self.meta), encoding="utf-8")
        self.prepare()
        subject.write_new(self.root / "annotation.json", annotation())
        selection = dict(protocol_id=subject.load_recipe()["protocol_id"], predictions_viewed=False, review_confirmed=True,
            device=dict(power_mode_id=1, clocks="preserve_original_DVFS_controls"),
            clips=[dict(pairs=dict(path="pair/pairs.json", sha256=subject.digest(self.output / "pairs.json")),
                        annotation=dict(path="annotation.json", sha256=subject.digest(self.root / "annotation.json")))])
        subject.write_new(self.root / "selection.json", selection)
        value = subject.freeze(self.root / "selection.json", self.root / "frozen")
        self.assertEqual(len(value["jobs"]), 4)
        self.assertEqual(value["status"], "INPUTS_FROZEN_EXECUTION_NOT_AUTHORIZED")
        self.assertTrue(all(job["status"] == "NOT_RUN" for job in value["jobs"]))
        with self.assertRaises(ValueError):
            subject.freeze(self.root / "selection.json", self.root / "frozen")


if __name__ == "__main__":
    unittest.main()
