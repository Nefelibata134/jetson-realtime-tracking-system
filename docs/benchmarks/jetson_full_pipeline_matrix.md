# Jetson Full Pipeline Performance Matrix

All runs use locked clocks and the complete detection, tracking, event evidence, and annotated video pipeline.
Capture resolution changes while the YOLOX model input remains 416x416.

## Critical Path

| Status | Capture | Power | Encoder | kbps | FPS | Drop % | Queue P95 | Pre P95 | TRT P95 | Post P95 | Track P95 | Event P95 | Active I/O P95 | E2E P95 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PASS | 720p | 25W (1) | mp4v | 0 | 30.03 | 0.00 | 0.47 | 2.44 | 3.53 | 0.39 | 0.06 | 0.01 | 15.98 | 9.99 |
| PASS | 720p | MAXN_SUPER (2) | mp4v | 0 | 30.04 | 0.00 | 0.43 | 1.92 | 3.22 | 0.31 | 0.06 | 0.01 | 12.32 | 8.46 |
| PASS | 1080p | 25W (1) | mp4v | 0 | 30.04 | 0.00 | 1.10 | 3.19 | 3.49 | 0.39 | 0.07 | 0.01 | 33.78 | 14.17 |
| PASS | 1080p | 25W (1) | x264 | 10000 | 30.00 | 0.00 | 1.06 | 2.47 | 3.75 | 0.41 | 0.00 | 0.00 | 0.00 | 13.67 |
| PASS | 1080p | MAXN_SUPER (2) | mp4v | 0 | 29.99 | 0.00 | 1.00 | 2.12 | 3.24 | 0.30 | 0.05 | 0.01 | 29.58 | 12.13 |
| PASS | 1080p | MAXN_SUPER (2) | x264 | 10000 | 29.12 | 0.00 | 1.20 | 2.48 | 6.31 | 0.32 | 0.06 | 0.01 | 30.18 | 14.45 |

Latencies are milliseconds. Active I/O includes only frames that emitted a new event; inspect its sample count in the CSV.

## Background Output And Device

| Capture | Power | Encoder | kbps | Events | Snapshots | Clips | Clip ms/frame | Video written/dropped | Video ms/frame | Flush ms | Mean W | GPU max % | GPU max C | RAM max MiB |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 720p | 25W (1) | mp4v | 0 | 2 | 2 | 2 | 31.21 | 600/0 | 30.93 | 1.60 | 8.69 | 33.00 | 57.31 | 2981.00 |
| 720p | MAXN_SUPER (2) | mp4v | 0 | 2 | 2 | 2 | 25.14 | 600/0 | 23.05 | 1.56 | 9.00 | 14.00 | 56.66 | 3027.00 |
| 1080p | 25W (1) | mp4v | 0 | 2 | 2 | 2 | 69.93 | 280/320 | 72.30 | 184.99 | 8.93 | 15.00 | 56.78 | 3453.00 |
| 1080p | 25W (1) | x264 | 10000 | 0 | 0 | 0 | n/a | 600/0 | 6.66 | 2.18 | 9.35 | 17.00 | 58.59 | 2684.00 |
| 1080p | MAXN_SUPER (2) | mp4v | 0 | 2 | 2 | 2 | 51.50 | 379/221 | 53.26 | 73.72 | 9.46 | 14.00 | 56.88 | 3400.00 |
| 1080p | MAXN_SUPER (2) | x264 | 10000 | 2 | 2 | 2 | 47.06 | 600/0 | 7.45 | 1.93 | 9.92 | 16.00 | 58.66 | 3038.00 |

Background encode time is worker execution time divided by frames actually written; it is workload, not main-thread latency.
