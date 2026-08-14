# MOT17 Evaluation Protocol

## Scope

The benchmark evaluates the complete YOLOX-Nano TensorRT and ByteTrack
pipeline on pedestrian sequences from the MOT17 training split. Metrics are
computed with the official TrackEval implementation pinned to commit
`12c8791b303e0a0b50f753af204249e622d0281a`.

MOT17 stores each physical video three times with DPM, FRCNN, and SDP public
detections. This runtime supplies its own YOLOX detections, so the protocol
uses only the FRCNN-named copy of each physical video. This prevents identical
frames and ground truth from being counted three times.

## Data Partition

| Partition | Sequences | Purpose |
| --- | --- | --- |
| Calibration | 02, 04, 05, 10 | Controlled tracker parameter comparison |
| Holdout | 09, 11, 13 | Final result reported once after configuration selection |

The tracked sequence maps are stored in `configs/mot17/`. Test-set labels are
not public and are not used by this local benchmark. Dataset validation checks
the selected sequence metadata, ground truth, image count, and frame numbering
before inference or metric computation begins.

## Frame Policy

- Every image in each selected sequence is processed in order.
- No bounded capture queue or frame dropping is used.
- Only COCO class 0 (`person`) is passed to ByteTrack.
- MOTChallenge frame indices and bounding-box origins are written as 1-based
  values.
- Result rows contain exactly ten MOTChallenge fields.

## Reproduction

Fetch the official data and pinned evaluator:

```bash
sudo apt-get install -y python3-numpy python3-scipy unzip wget
bash scripts/fetch_mot17.sh
bash scripts/fetch_trackeval.sh
```

The pinned evaluator uses NumPy APIs retained by Ubuntu 22.04's system
packages. Installing an unpinned current NumPy release is intentionally
avoided for this benchmark.

Build the target-device inference binary:

```bash
cmake -S . -B build-mot17 \
  -DCMAKE_BUILD_TYPE=Release \
  -DEDGE_VISION_ENABLE_TENSORRT=ON
cmake --build build-mot17 -j"$(nproc)"
```

Run the calibration sequences, select one configuration, then generate the
holdout tracker files:

```bash
bash scripts/run_mot17_inference.sh \
  --engine models/yolox_nano_fp16.plan \
  --seqmap configs/mot17/calibration.txt

bash scripts/run_mot17_inference.sh \
  --engine models/yolox_nano_fp16.plan \
  --seqmap configs/mot17/holdout.txt
```

Compute the official holdout metrics and create the compact report:

```bash
bash scripts/run_trackeval_mot17.sh \
  --seqmap configs/mot17/holdout.txt

python3 scripts/summarize_mot17.py \
  --summary reports/mot17/trackeval/edge_vision/pedestrian_summary.txt \
  --json reports/mot17/holdout_metrics.json \
  --markdown reports/mot17/holdout_metrics.md \
  --title "MOT17 Holdout Evaluation"
```

TrackEval reports HOTA, IDF1, MOTA, and ID switches. HOTA balances detection
and association quality, IDF1 measures identity consistency, MOTA combines
false positives, missed detections, and identity switches, and ID switches
count identity continuity failures.

The wrapper copies the selected sequence list to
`data/mot17/train/seqmaps/MOT17-train.txt`, the canonical path expected by the
pinned TrackEval command-line runner. This avoids passing its legacy
`SEQMAP_FILE` option, which parses a single path as a list at this revision.
