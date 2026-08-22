# Stability And Recovery Validation

The runtime is validated as a supervised service rather than as a single
successful command. A baseline soak establishes steady behavior, while
separate process and source fault injections verify automatic recovery.

## Health Model

A live process is not sufficient evidence of a healthy video service. The
validation checks three independent layers:

1. systemd reports the service as active, running, and ready.
2. `WatchdogTimestampMonotonic` advances only when real frames arrive.
3. line-buffered frame records continue to appear in the runtime log.

The collector also samples the service PID, restart counter, process memory,
task count, spool size, free disk space, power, GPU utilization, and
temperature. It does not modify the inference thread or its timing boundaries.

## Baseline Soak

Restart the normal 720p/25W service immediately before collection so the
runtime generation and sampled soak windows align, then run:

```bash
sudo systemctl restart edge-vision.service
sudo python3 scripts/collect_service_soak.py \
  --duration-seconds 3600 \
  --sample-interval-seconds 30 \
  --output-root reports/stability/raw
```

For an SSH session that may disconnect, authenticate first and detach only the
collector. Its first log line records the run directory:

```bash
sudo -v
sudo nohup python3 scripts/collect_service_soak.py \
  --duration-seconds 3600 \
  --sample-interval-seconds 30 \
  --output-root reports/stability/raw \
  > /tmp/edge-vision-soak-collector.log 2>&1 &
head -n 1 /tmp/edge-vision-soak-collector.log
```

The command prints a `run_directory`. After collection completes, promptly
gracefully stop the generation, copy its atomically published final metrics,
summarize the run, and restore the service:

```bash
run_dir=reports/stability/raw/service_soak_TIMESTAMP_PID
sudo bash scripts/finalize_service_soak.sh --run-dir "$run_dir"
cat "$run_dir/report.md"
```

The baseline passes when the requested duration is covered, the same service
generation remains active, watchdog and frame progress continue, temperature
and disk stay within limits, memory has no sustained upward trend, and final
runtime metrics retain at least 25 FPS with at most 1% steady-state capture
drops. Final metrics must show a clean SIGTERM shutdown.

If finalization is delayed, live samples still describe the exact requested
soak interval, while final runtime counters cover the longer process
generation. The report estimates and discloses both windows rather than
silently treating them as identical.

Raw `samples.jsonl` and `tegrastats.log` remain under the ignored `reports/`
tree. A compact reviewed report can be published separately.

## Process Crash Injection

The process test sends SIGKILL only to the main process. It passes only after
systemd creates a new PID and session, increments `NRestarts`, reports ready,
and receives a watchdog heartbeat backed by new frames:

```bash
sudo python3 scripts/inject_service_crash.py \
  --output reports/stability/process_crash.json
```

This test is intentionally separate from the baseline soak because a planned
fault would otherwise invalidate the zero-restart baseline criterion.

## RTSP Source Outage

Use an H.264 MP4 replay so the outage is repeatable and does not depend on an
external camera server:

```bash
python3 scripts/inject_rtsp_outage.py \
  --video videos/session_h264.mp4 \
  --engine models/yolox_nano_fp16.plan \
  --binary build-stability/edge_vision_realtime_detect
```

The harness starts a local RTSP server, interrupts it during inference,
restarts it, and checks the runtime summary. A socket reopen alone is not
counted as recovery: `restart_successes`, `stream_generation`, and
`tracker_resets` must advance after actual decoded frames arrive, and the
requested frame target must still be reached.

## Evidence Boundaries

- Sampled log latency is a periodic health trace, not a percentile over every
  frame. The final runtime JSON provides the complete bounded latency window.
- A flat start/end memory comparison can miss a temporary peak; the report
  includes maximum memory and a least-squares steady-state slope.
- One soak run establishes evidence for one hardware, power, source, and
  configuration combination. It does not prove every deployment environment.
