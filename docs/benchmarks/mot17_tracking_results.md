# MOT17 Tracking Evaluation Results

## System Under Test

- Platform: NVIDIA Jetson Orin Nano 8GB
- Detector input: `1x3x416x416`
- Runtime: TensorRT FP16 with the C++ inference pipeline
- Tracker: ByteTrack with class-aware association
- Evaluator: TrackEval commit `12c8791b303e0a0b50f753af204249e622d0281a`
- Frame policy: sequential processing without frame dropping

MOT17 training sequences are partitioned before parameter selection. Sequences
02, 04, 05, and 10 form the calibration partition. Sequences 09, 11, and 13
form the holdout partition, which is evaluated once after configuration
selection. Only the FRCNN-named copy of each physical video is used.

## Configuration Selection

YOLOX-Nano and YOLOX-Tiny use the same postprocessing and ByteTrack settings:

| Parameter | Value |
| --- | ---: |
| Detector score threshold | 0.10 |
| NMS threshold | 0.45 |
| Track threshold | 0.30 |
| New-track threshold | 0.40 |
| Match threshold | 0.80 |
| Track buffer | 30 frames |

| Model | HOTA | IDF1 | MOTA | ID switches |
| --- | ---: | ---: | ---: | ---: |
| YOLOX-Nano FP16 | 29.19 | 34.50 | 24.38 | 227 |
| YOLOX-Tiny FP16 | **33.31** | **39.80** | **29.65** | 232 |

YOLOX-Tiny is selected because it improves HOTA by 4.12 points, IDF1 by 5.30
points, and MOTA by 5.27 points while retaining real-time target-device
throughput. The five additional identity switches do not offset the broader
detection and association improvement.

## Final Holdout Result

| HOTA | DetA | AssA | IDF1 | MOTA | Recall | Precision | ID switches |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **38.89** | 35.26 | 43.36 | **46.75** | **39.19** | 46.00 | 87.93 | 132 |

| True positives | False negatives | False positives | GT detections | Output detections |
| ---: | ---: | ---: | ---: | ---: |
| 12,146 | 14,257 | 1,667 | 26,403 | 13,813 |

All 2,175 holdout frames were processed. Sequence-level TensorRT inference
P95 ranged from 13.98 to 14.07 ms, ByteTrack P95 ranged from 0.28 to 0.32 ms,
and effective throughput ranged from 30.54 to 33.00 FPS.

The holdout partition has higher detection recall than the calibration
partition, so its aggregate tracking metrics are also higher. This difference
reflects sequence difficulty rather than post-holdout tuning. Precision remains
high, while missed detections and identity switches remain the principal
accuracy limitations.

Reproduction commands and the fixed data split are defined in the
[evaluation protocol](mot17_evaluation_protocol.md). Compact source values are
also available in [`mot17_tracking_results.csv`](mot17_tracking_results.csv).
