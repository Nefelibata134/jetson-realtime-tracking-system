# Jetson Service Stability Validation

This report validates the supervised 720p CSI configuration with an IMX219,
YOLOX-Nano FP16 TensorRT detection, ByteTrack association, safety events,
local evidence persistence, telemetry, and systemd watchdog supervision.

## Acceptance Result

| Check | Result |
| --- | --- |
| 60-minute baseline soak | PASS |
| Main-process SIGKILL recovery | PASS |
| Controlled RTSP source outage | PASS |
| C++ regression suite | 15/15 passed |
| Python operations tests | 23/23 passed |

Raw logs, event evidence, and captured video remain in ignored runtime
directories and are not part of the repository.

## Baseline Soak

The external collector sampled systemd state, watchdog progress, line-buffered
frame records, process resources, persistent spool size, disk capacity, and
Jetson telemetry every 30 seconds.

| Duration | Samples | Active | PID changes | Restarts | Watchdog stalls | Frame stalls |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 60.00 min | 121 | 100.00% | 0 | 0 | 0 | 0 |

| RAM start | RAM max | RAM end | Steady growth | Slope | Spool growth | Min free disk | Mean power | Max GPU/TJ C |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 299.56 MiB | 735.94 MiB | 352.84 MiB | 52.72 MiB | 1.121 MiB/min | 9.47 MiB | 198.07 GiB | 7.32 W | 59.03 C |

The memory peak was transient and returned close to its baseline. Its size and
the simultaneous persistent-spool growth are consistent with bounded raw-frame
buffers being active while pre/post-event clips were assembled. The one-hour
run stayed below the 256 MiB steady-growth and 2 MiB/min slope gates; a longer
run is still required before claiming absence of every slow leak.

The process was finalized after the exact collector window had ended. Its
final runtime aggregate therefore covered an estimated 154.5-minute service
generation rather than only the sampled hour:

| Measured frames | FPS | Capture drop | TRT P95 | E2E P95 |
| ---: | ---: | ---: | ---: | ---: |
| 278,089 | 30.00 | 0.00% | 8.36 ms | 16.30 ms |

The longer aggregate remains useful for throughput and latency evidence, but
the 121 external samples are the authoritative one-hour stability window.

## Process Crash Recovery

The main process received SIGKILL while systemd remained responsible for the
unit:

| Old PID | New PID | Restart delta | New session | Ready | Frame watchdog |
| ---: | ---: | ---: | --- | --- | --- |
| 4054 | 4288 | +1 | yes | yes | advanced |

Recovery was accepted only after a new process and session reported ready and
advanced the watchdog timestamp from subsequent real frames.

## RTSP Source Recovery

A local H.264 RTSP replay server was stopped for two seconds during inference
and then restarted:

| Target | Attempts | Real-frame successes | Stream generation | Tracker resets | Recovery exhausted |
| ---: | ---: | ---: | ---: | ---: | --- |
| 180 frames | 4 | 1 | 1 | 1 | no |

The runtime reached the requested target after recovery. Overall effective
throughput was 21.08 FPS because wall time included the intentional outage and
retry delay; TensorRT P95 remained 8.28 ms and end-to-end P95 was 19.02 ms.
Empty socket reopens were not counted as successful recovery.

## Evidence Boundary

The result covers one Jetson, one IMX219, one model and service configuration,
one hour of baseline operation, a main-process crash, and a local RTSP outage.
It does not replace multi-day endurance testing, physical camera disconnect
testing, storage-exhaustion testing, or recovery over a lossy remote network.
