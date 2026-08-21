#!/usr/bin/env bash
set -euo pipefail

binary="${EDGE_VISION_BINARY:-/opt/edge-vision/bin/edge_vision_realtime_detect}"
engine="${EDGE_VISION_ENGINE:-/var/lib/edge-vision/models/yolox_nano_fp16.plan}"
state_directory="${STATE_DIRECTORY:-/var/lib/edge-vision}"
source_type="${EDGE_VISION_SOURCE:-csi}"

test -x "$binary" || {
  echo "runtime binary is not executable: $binary" >&2
  exit 1
}
test -r "$engine" || {
  echo "TensorRT engine is not readable: $engine" >&2
  exit 1
}

session_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
session_directory="$state_directory/spool/$session_id"
mkdir -p \
  "$session_directory/snapshots" \
  "$session_directory/clips" \
  "$state_directory/metrics"
ln -sfn "$session_directory" "$state_directory/current"

args=(
  --engine "$engine"
  --continuous
  --warmup-frames "${EDGE_VISION_WARMUP_FRAMES:-30}"
  --queue-capacity "${EDGE_VISION_QUEUE_CAPACITY:-2}"
  --score-threshold "${EDGE_VISION_SCORE_THRESHOLD:-0.3}"
  --nms-threshold "${EDGE_VISION_NMS_THRESHOLD:-0.45}"
  --track-threshold "${EDGE_VISION_TRACK_THRESHOLD:-0.5}"
  --new-track-threshold "${EDGE_VISION_NEW_TRACK_THRESHOLD:-0.6}"
  --track-buffer "${EDGE_VISION_TRACK_BUFFER:-30}"
  --metrics-json "$state_directory/metrics/latest.json"
  --metrics-window-frames "${EDGE_VISION_METRICS_WINDOW_FRAMES:-4096}"
  --tegrastats-interval-ms "${EDGE_VISION_TEGRASTATS_INTERVAL_MS:-500}"
  --log-interval "${EDGE_VISION_LOG_INTERVAL:-300}"
  --reconnect-attempts "${EDGE_VISION_RECONNECT_ATTEMPTS:-3}"
  --reconnect-delay-ms "${EDGE_VISION_RECONNECT_DELAY_MS:-1000}"
)

case "$source_type" in
  csi)
    args+=(
      --csi
      --sensor-id "${EDGE_VISION_SENSOR_ID:-0}"
      --sensor-mode "${EDGE_VISION_SENSOR_MODE:-4}"
      --capture-width "${EDGE_VISION_CAPTURE_WIDTH:-1280}"
      --capture-height "${EDGE_VISION_CAPTURE_HEIGHT:-720}"
      --capture-fps "${EDGE_VISION_CAPTURE_FPS:-60}"
      --width "${EDGE_VISION_WIDTH:-1280}"
      --height "${EDGE_VISION_HEIGHT:-720}"
      --fps "${EDGE_VISION_FPS:-30}"
    )
    ;;
  rtsp)
    : "${EDGE_VISION_RTSP_URI:?EDGE_VISION_RTSP_URI is required for RTSP}"
    args+=(
      --rtsp "$EDGE_VISION_RTSP_URI"
      --rtsp-transport "${EDGE_VISION_RTSP_TRANSPORT:-tcp}"
      --rtsp-latency-ms "${EDGE_VISION_RTSP_LATENCY_MS:-200}"
      --rtsp-timeout-ms "${EDGE_VISION_RTSP_TIMEOUT_MS:-5000}"
      --width "${EDGE_VISION_WIDTH:-1280}"
      --height "${EDGE_VISION_HEIGHT:-720}"
      --fps "${EDGE_VISION_FPS:-30}"
    )
    ;;
  file)
    : "${EDGE_VISION_FILE:?EDGE_VISION_FILE is required for file input}"
    args+=(
      --file "$EDGE_VISION_FILE"
      --width "${EDGE_VISION_WIDTH:-1280}"
      --height "${EDGE_VISION_HEIGHT:-720}"
      --fps "${EDGE_VISION_FPS:-30}"
    )
    ;;
  *)
    echo "EDGE_VISION_SOURCE must be csi, rtsp, or file" >&2
    exit 1
    ;;
esac

rules_enabled=0
if [[ -n "${EDGE_VISION_EVENT_ROI:-}" ]]; then
  read -r -a roi <<<"$EDGE_VISION_EVENT_ROI"
  [[ ${#roi[@]} -eq 4 ]] || {
    echo "EDGE_VISION_EVENT_ROI requires four coordinates" >&2
    exit 1
  }
  args+=(--event-roi "${roi[@]}")
  rules_enabled=1
fi
if [[ -n "${EDGE_VISION_EVENT_LINE:-}" ]]; then
  read -r -a line <<<"$EDGE_VISION_EVENT_LINE"
  [[ ${#line[@]} -eq 4 ]] || {
    echo "EDGE_VISION_EVENT_LINE requires four coordinates" >&2
    exit 1
  }
  args+=(
    --event-line "${line[@]}"
    --event-line-direction "${EDGE_VISION_EVENT_LINE_DIRECTION:-any}"
  )
  rules_enabled=1
fi
if [[ -n "${EDGE_VISION_EVENT_DWELL_SECONDS:-}" ]]; then
  args+=(--event-dwell-seconds "$EDGE_VISION_EVENT_DWELL_SECONDS")
fi

if [[ $rules_enabled -eq 1 ]]; then
  args+=(
    --event-class-id "${EDGE_VISION_EVENT_CLASS_ID:-0}"
    --event-jsonl "$session_directory/events.jsonl"
    --event-snapshot-dir "$session_directory/snapshots"
    --event-clip-dir "$session_directory/clips"
    --event-clip-pre-seconds "${EDGE_VISION_EVENT_CLIP_PRE_SECONDS:-2}"
    --event-clip-post-seconds "${EDGE_VISION_EVENT_CLIP_POST_SECONDS:-3}"
  )
fi

echo "session_directory=$session_directory"
exec stdbuf -oL -eL "$binary" "${args[@]}"
