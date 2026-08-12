# Jetson Detection Performance Matrix

Each row uses the latest run for a model, capture resolution, and power mode.
The first three and final telemetry samples are excluded from power and temperature summaries.
Model input remains fixed at 416x416; resolution refers to the CSI capture stream.

| Status | Model | Capture | Power mode | FPS | P95 infer ms | P95 e2e ms | Drop % | Mean W | FPS/W | Max GPU C |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PASS | nano | 720p | 25W (1) | 30.05 | 6.34 | 6.77 | 0.00 | 7.94 | 3.78 | 54.62 |
| PASS | nano | 720p | MAXN_SUPER (2) | 30.05 | 5.47 | 5.90 | 0.00 | 8.23 | 3.65 | 54.53 |
| PASS | nano | 1080p | 25W (1) | 30.01 | 6.30 | 7.29 | 0.00 | 7.94 | 3.78 | 55.12 |
| PASS | nano | 1080p | MAXN_SUPER (2) | 30.05 | 5.49 | 6.59 | 0.00 | 8.22 | 3.66 | 55.25 |
| PASS | tiny | 720p | 25W (1) | 30.04 | 6.94 | 7.37 | 0.00 | 8.25 | 3.64 | 55.88 |
| PASS | tiny | 720p | MAXN_SUPER (2) | 30.05 | 6.11 | 6.51 | 0.00 | 8.58 | 3.50 | 55.94 |
| PASS | tiny | 1080p | 25W (1) | 30.05 | 6.99 | 8.00 | 0.00 | 8.24 | 3.65 | 56.34 |
| PASS | tiny | 1080p | MAXN_SUPER (2) | 30.05 | 6.04 | 7.09 | 0.00 | 8.57 | 3.51 | 56.56 |
