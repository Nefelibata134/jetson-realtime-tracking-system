# Headless Service Operations

The runtime can be installed as a systemd service for unattended Jetson
operation. The service uses the same TensorRT, GStreamer, ByteTrack, event, and
telemetry code paths as the command-line runtime.

The main service deliberately does not enable systemd `PrivateTmp`. NVIDIA
Argus camera capture communicates through a host-managed endpoint under
`/tmp`, so an isolated temporary directory would prevent `nvarguscamerasrc`
from reaching the camera daemon. The spool-pruning service does not use the
camera and keeps its temporary-directory isolation.

## Lifecycle

```text
systemd start
  -> launcher creates a persistent session directory
  -> runtime opens the source and reports READY=1
  -> each received frame refreshes watchdog progress
  -> no frame progress causes watchdog expiry and restart
  -> SIGTERM requests orderly shutdown
  -> capture, evidence, video, telemetry, and metrics finish
  -> runtime reports STOPPING=1 and exits successfully
```

The signal handler only records the signal number. The main thread wakes from
its timed queue wait, observes the request, and performs resource cleanup in
normal C++ control flow. This avoids calling locks, allocators, GStreamer, or
file I/O from asynchronous signal context.

## Install

Build the Jetson runtime first, then install the binary and the device-built
TensorRT engine:

```bash
sudo apt-get update
sudo apt-get install -y logrotate

cmake -S . -B build-service \
  -DCMAKE_BUILD_TYPE=Release \
  -DEDGE_VISION_ENABLE_GSTREAMER=ON \
  -DEDGE_VISION_ENABLE_TENSORRT=ON
cmake --build build-service -j"$(nproc)"

sudo bash scripts/install_systemd_service.sh \
  --binary build-service/edge_vision_realtime_detect \
  --engine models/yolox_nano_fp16.plan
```

The installer creates the unprivileged `edge-vision` account, installs files
under `/opt/edge-vision`, copies the engine into persistent state, and enables
the service and retention timer. It does not start the video pipeline before
the configuration is reviewed.

Edit `/etc/edge-vision/edge-vision.env`, then start the service:

```bash
sudo systemctl start edge-vision.service
sudo systemctl status edge-vision.service --no-pager
sudo systemctl enable --now edge-vision-prune.timer
```

The default configuration selects IMX219 sensor mode 4 at 1280x720/60 FPS and
delivers 30 FPS to the application. RTSP and file sources use the same launcher
with `EDGE_VISION_SOURCE=rtsp` or `EDGE_VISION_SOURCE=file` and their required
path variables.

## Persistent State

```text
/var/lib/edge-vision/
  models/yolox_nano_fp16.plan
  metrics/latest.json
  current -> spool/<session-id>
  spool/<session-id>/
    events.jsonl
    snapshots/
    clips/
```

Each process generation writes a separate session. Network availability is not
required for journal or evidence publication. Restarting the service creates a
new session without overwriting earlier evidence.

`edge-vision-prune.timer` removes the oldest completed sessions when they are
older than `EDGE_VISION_SPOOL_MAX_AGE_DAYS` or total retained data exceeds
`EDGE_VISION_SPOOL_MAX_BYTES`. The current session and newest completed session
are protected. The service has a 24-hour maximum generation, which periodically
closes the active journal and allows complete-session retention to remain
bounded.

## Watchdog And Shutdown

The unit uses `Type=notify` and `WatchdogSec=30`. A heartbeat is sent only when
a real frame arrived within half of the watchdog interval. A connected RTSP
socket that produces no decodable frames therefore cannot keep the service
healthy indefinitely.

Verify a graceful stop:

```bash
sudo systemctl stop edge-vision.service
sudo systemctl show edge-vision.service \
  -p Result -p ExecMainStatus -p ActiveState
cat /var/lib/edge-vision/metrics/latest.json
```

The expected result is `Result=success`, `ExecMainStatus=0`, and a metrics
status with `shutdown_requested: true` and `shutdown_signal: 15`.

Verify restart behavior by stopping frame progress long enough to exceed the
watchdog interval, then inspect:

```bash
systemctl show edge-vision.service \
  -p NRestarts -p Result -p WatchdogTimestampMonotonic
```

## Logs

Runtime output is written to `/var/log/edge-vision/runtime.log`. The installed
logrotate policy rotates daily or at 20 MiB, retains seven compressed
generations, and uses `copytruncate` because stdout remains open for the life
of the process. systemd opens the append target as root before launching the
unprivileged service, so logrotate retains root privileges for this file.

```bash
sudo logrotate -d /etc/logrotate.d/edge-vision
tail -n 100 /var/log/edge-vision/runtime.log
```

systemd start, stop, watchdog, and exit-state messages remain available through
the journal:

```bash
journalctl -u edge-vision.service --since today --no-pager
```
