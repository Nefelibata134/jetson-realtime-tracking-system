#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  scripts/run_pipeline_benchmark.sh \
    --model nano|tiny|s \
    --engine models/model.plan \
    --resolution 720p|1080p \
    [--frames 600] [--warmup-frames 30] \
    [--output-encoder x264|mp4v] [--output-bitrate-kbps 10000]

The benchmark uses CSI input and enables tracking, event evidence, annotated
video output, runtime metrics, and Jetson telemetry. Select the nvpmodel mode
and run sudo jetson_clocks before invoking this script.
EOF
}

model=""
engine=""
resolution=""
frames=600
warmup_frames=30
queue_capacity=2
output_queue_capacity=4
output_encoder="x264"
output_bitrate_kbps=10000
score_threshold=0.25
nms_threshold=0.45
track_threshold=0.50
new_track_threshold=0.60
track_buffer=30
output_dir="reports/benchmarks/pipeline/raw"
artifact_dir="outputs/benchmarks/pipeline"
binary="./build-pipeline-benchmark/edge_vision_realtime_detect"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model) model="$2"; shift 2 ;;
        --engine) engine="$2"; shift 2 ;;
        --resolution) resolution="$2"; shift 2 ;;
        --frames) frames="$2"; shift 2 ;;
        --warmup-frames) warmup_frames="$2"; shift 2 ;;
        --queue-capacity) queue_capacity="$2"; shift 2 ;;
        --output-queue-capacity) output_queue_capacity="$2"; shift 2 ;;
        --output-encoder) output_encoder="$2"; shift 2 ;;
        --output-bitrate-kbps) output_bitrate_kbps="$2"; shift 2 ;;
        --score-threshold) score_threshold="$2"; shift 2 ;;
        --nms-threshold) nms_threshold="$2"; shift 2 ;;
        --output-dir) output_dir="$2"; shift 2 ;;
        --artifact-dir) artifact_dir="$2"; shift 2 ;;
        --binary) binary="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ -z "${model}" || -z "${engine}" || -z "${resolution}" ]]; then
    usage >&2
    exit 2
fi
if [[ "${model}" != "nano" && "${model}" != "tiny" && "${model}" != "s" ]]; then
    echo "--model must be nano, tiny, or s" >&2
    exit 2
fi
if [[ "${output_encoder}" != "x264" && "${output_encoder}" != "mp4v" ]]; then
    echo "--output-encoder must be x264 or mp4v" >&2
    exit 2
fi
if [[ ! "${output_bitrate_kbps}" =~ ^[1-9][0-9]*$ ]]; then
    echo "--output-bitrate-kbps must be a positive integer" >&2
    exit 2
fi
if [[ ! -x "${binary}" ]]; then
    echo "Runtime binary does not exist: ${binary}" >&2
    exit 1
fi
if [[ ! -f "${engine}" ]]; then
    echo "TensorRT engine does not exist: ${engine}" >&2
    exit 1
fi
if ! command -v tegrastats >/dev/null 2>&1; then
    echo "tegrastats was not found" >&2
    exit 1
fi
if [[ "${output_encoder}" == "x264" ]] &&
    { ! command -v gst-inspect-1.0 >/dev/null 2>&1 ||
      ! gst-inspect-1.0 x264enc >/dev/null 2>&1; }; then
    echo "x264enc is unavailable; install gstreamer1.0-tools and gstreamer1.0-plugins-ugly" >&2
    exit 1
fi
if systemctl is-active --quiet edge-vision.service 2>/dev/null; then
    echo "edge-vision.service is using the camera; stop it before benchmarking" >&2
    exit 1
fi

case "${resolution}" in
    720p)
        sensor_mode=4
        capture_width=1280
        capture_height=720
        capture_fps=60
        output_width=1280
        output_height=720
        output_fps=30
        ;;
    1080p)
        sensor_mode=2
        capture_width=1920
        capture_height=1080
        capture_fps=30
        output_width=1920
        output_height=1080
        output_fps=30
        ;;
    *)
        echo "--resolution must be 720p or 1080p" >&2
        exit 2
        ;;
esac

power_query="$(nvpmodel -q)"
power_mode="$(printf '%s\n' "${power_query}" | awk -F': ' '/NV Power Mode/{print $2; exit}')"
power_mode_id="$(printf '%s\n' "${power_query}" | awk '/^[[:space:]]*[0-9]+[[:space:]]*$/{gsub(/[[:space:]]/, ""); print; exit}')"
if [[ -z "${power_mode}" || -z "${power_mode_id}" ]]; then
    echo "Unable to parse the active nvpmodel mode" >&2
    printf '%s\n' "${power_query}" >&2
    exit 1
fi

gpu_min=""
gpu_max=""
for gpu_devfreq in \
    /sys/class/devfreq/*gpu* \
    /sys/devices/platform/*.gpu/devfreq/*; do
    if [[ -r "${gpu_devfreq}/min_freq" && -r "${gpu_devfreq}/max_freq" ]]; then
        gpu_min="$(<"${gpu_devfreq}/min_freq")"
        gpu_max="$(<"${gpu_devfreq}/max_freq")"
        break
    fi
done
if [[ -z "${gpu_min}" || -z "${gpu_max}" || "${gpu_min}" != "${gpu_max}" ]]; then
    echo "Jetson clocks are not locked; run sudo jetson_clocks first" >&2
    exit 1
fi

mkdir -p "${output_dir}" "${artifact_dir}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
stem="${model}_${resolution}_${output_encoder}_mode-${power_mode_id}_${timestamp}"
run_dir="${artifact_dir}/${stem}"
runtime_log="${output_dir}/${stem}.runtime.txt"
metrics_json="${output_dir}/${stem}.metrics.json"
mkdir -p "${run_dir}/snapshots" "${run_dir}/clips"
engine_sha256="$(sha256sum "${engine}" | awk '{print $1}')"

set +e
{
    echo "benchmark_timestamp=${timestamp}"
    echo "benchmark_profile=full"
    echo "benchmark_model=${model}"
    echo "benchmark_resolution=${resolution}"
    echo "benchmark_output_encoder=${output_encoder}"
    echo "benchmark_output_bitrate_kbps=${output_bitrate_kbps}"
    echo "power_mode=${power_mode}"
    echo "power_mode_id=${power_mode_id}"
    echo "clocks_locked=true"
    echo "gpu_frequency_hz=${gpu_min}"
    echo "engine=${engine}"
    echo "engine_sha256=${engine_sha256}"
    echo "requested_warmup_frames=${warmup_frames}"
    echo "requested_measured_frames=${frames}"
    echo "artifact_directory=${run_dir}"

    "${binary}" \
        --engine "${engine}" \
        --csi --sensor-id 0 \
        --sensor-mode "${sensor_mode}" \
        --capture-width "${capture_width}" \
        --capture-height "${capture_height}" \
        --capture-fps "${capture_fps}" \
        --width "${output_width}" \
        --height "${output_height}" \
        --fps "${output_fps}" \
        --warmup-frames "${warmup_frames}" \
        --frames "${frames}" \
        --queue-capacity "${queue_capacity}" \
        --score-threshold "${score_threshold}" \
        --nms-threshold "${nms_threshold}" \
        --track-threshold "${track_threshold}" \
        --new-track-threshold "${new_track_threshold}" \
        --track-buffer "${track_buffer}" \
        --event-roi 0 0 1 1 \
        --event-dwell-seconds 2 \
        --event-class-id -1 \
        --event-jsonl "${run_dir}/events.jsonl" \
        --event-snapshot-dir "${run_dir}/snapshots" \
        --event-clip-dir "${run_dir}/clips" \
        --event-clip-pre-seconds 1 \
        --event-clip-post-seconds 1 \
        --output-video "${run_dir}/annotated.mp4" \
        --output-encoder "${output_encoder}" \
        --output-bitrate-kbps "${output_bitrate_kbps}" \
        --output-queue-capacity "${output_queue_capacity}" \
        --metrics-json "${metrics_json}" \
        --tegrastats-interval-ms 500 \
        --log-interval 300 \
        --reconnect-attempts 3 \
        --reconnect-delay-ms 1000
    runtime_status=$?
    echo "runtime_exit_code=${runtime_status}"
    exit "${runtime_status}"
} 2>&1 | tee "${runtime_log}"
runtime_status=${PIPESTATUS[0]}
set -e

echo "runtime_log=${runtime_log}"
echo "metrics_json=${metrics_json}"
echo "artifact_directory=${run_dir}"
exit "${runtime_status}"
