#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  scripts/run_jetson_benchmark.sh \
    --model nano|tiny|s \
    --engine models/model.plan \
    --resolution 720p|1080p \
    [--frames 600] [--warmup-frames 30]

The script records the active nvpmodel mode. Change power mode before running
the command; the script does not modify device power settings.
EOF
}

model=""
engine=""
resolution=""
frames=600
warmup_frames=30
queue_capacity=2
score_threshold=0.25
nms_threshold=0.45
output_dir="reports/benchmarks/raw"
binary="./build-jetson-benchmark/edge_vision_realtime_detect"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model) model="$2"; shift 2 ;;
        --engine) engine="$2"; shift 2 ;;
        --resolution) resolution="$2"; shift 2 ;;
        --frames) frames="$2"; shift 2 ;;
        --warmup-frames) warmup_frames="$2"; shift 2 ;;
        --queue-capacity) queue_capacity="$2"; shift 2 ;;
        --score-threshold) score_threshold="$2"; shift 2 ;;
        --nms-threshold) nms_threshold="$2"; shift 2 ;;
        --output-dir) output_dir="$2"; shift 2 ;;
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
if [[ ! -x "${binary}" ]]; then
    echo "Runtime binary does not exist: ${binary}" >&2
    exit 1
fi
if [[ ! -f "${engine}" ]]; then
    echo "TensorRT engine does not exist: ${engine}" >&2
    exit 1
fi
if ! command -v tegrastats >/dev/null 2>&1; then
    echo "tegrastats was not found." >&2
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

power_query="$(sudo nvpmodel -q)"
power_mode="$(printf '%s\n' "${power_query}" | awk -F': ' '/NV Power Mode/{print $2; exit}')"
power_mode_id="$(printf '%s\n' "${power_query}" | awk '/^[[:space:]]*[0-9]+[[:space:]]*$/{gsub(/[[:space:]]/, ""); print; exit}')"
if [[ -z "${power_mode}" || -z "${power_mode_id}" ]]; then
    echo "Unable to parse the active nvpmodel mode:" >&2
    printf '%s\n' "${power_query}" >&2
    exit 1
fi

mkdir -p "${output_dir}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
stem="${model}_${resolution}_mode-${power_mode_id}_${timestamp}"
runtime_log="${output_dir}/${stem}.runtime.txt"
telemetry_log="${output_dir}/${stem}.tegrastats.txt"
engine_sha256="$(sha256sum "${engine}" | awk '{print $1}')"

tegrastats --interval 1000 >"${telemetry_log}" 2>&1 &
telemetry_pid=$!
cleanup() {
    if kill -0 "${telemetry_pid}" >/dev/null 2>&1; then
        kill "${telemetry_pid}" >/dev/null 2>&1 || true
    fi
    wait "${telemetry_pid}" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

set +e
{
    echo "benchmark_timestamp=${timestamp}"
    echo "benchmark_model=${model}"
    echo "benchmark_resolution=${resolution}"
    echo "power_mode=${power_mode}"
    echo "power_mode_id=${power_mode_id}"
    echo "engine=${engine}"
    echo "engine_sha256=${engine_sha256}"
    echo "requested_warmup_frames=${warmup_frames}"
    echo "requested_measured_frames=${frames}"

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
        --log-interval 300 \
        --reconnect-attempts 3 \
        --reconnect-delay-ms 1000
    runtime_status=$?
    echo "runtime_exit_code=${runtime_status}"
    exit "${runtime_status}"
} 2>&1 | tee "${runtime_log}"
runtime_status=${PIPESTATUS[0]}
set -e

cleanup
trap - EXIT INT TERM

echo "runtime_log=${runtime_log}"
echo "telemetry_log=${telemetry_log}"
exit "${runtime_status}"
