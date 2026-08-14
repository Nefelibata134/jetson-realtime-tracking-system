#!/usr/bin/env bash
set -euo pipefail

engine=""
data_root="data/mot17/train"
seqmap="configs/mot17/calibration.txt"
output_root="outputs/mot17/edge_vision/data"
report_root="reports/mot17/inference"
binary="./build-mot17/edge_vision_mot_sequence_infer"
score_threshold="0.10"
nms_threshold="0.45"
track_threshold="0.50"
new_track_threshold="0.60"
match_threshold="0.80"
track_buffer="30"

usage() {
    cat <<'EOF'
Usage:
  scripts/run_mot17_inference.sh --engine ENGINE [options]

Options:
  --data-root PATH
  --seqmap PATH
  --output-root PATH
  --report-root PATH
  --binary PATH
  --score-threshold VALUE
  --nms-threshold VALUE
  --track-threshold VALUE
  --new-track-threshold VALUE
  --match-threshold VALUE
  --track-buffer N
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --engine) engine="$2"; shift 2 ;;
        --data-root) data_root="$2"; shift 2 ;;
        --seqmap) seqmap="$2"; shift 2 ;;
        --output-root) output_root="$2"; shift 2 ;;
        --report-root) report_root="$2"; shift 2 ;;
        --binary) binary="$2"; shift 2 ;;
        --score-threshold) score_threshold="$2"; shift 2 ;;
        --nms-threshold) nms_threshold="$2"; shift 2 ;;
        --track-threshold) track_threshold="$2"; shift 2 ;;
        --new-track-threshold) new_track_threshold="$2"; shift 2 ;;
        --match-threshold) match_threshold="$2"; shift 2 ;;
        --track-buffer) track_buffer="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ -z "${engine}" ]]; then
    echo "--engine is required" >&2
    exit 2
fi
for path in "${engine}" "${seqmap}"; do
    if [[ ! -f "${path}" ]]; then
        echo "File does not exist: ${path}" >&2
        exit 1
    fi
done
if [[ ! -d "${data_root}" ]]; then
    echo "MOT17 training directory does not exist: ${data_root}" >&2
    exit 1
fi
if [[ ! -x "${binary}" ]]; then
    echo "Inference binary does not exist: ${binary}" >&2
    exit 1
fi

mkdir -p "${output_root}" "${report_root}"
sequence_count=0
while IFS= read -r sequence; do
    sequence="${sequence%$'\r'}"
    if [[ -z "${sequence}" || "${sequence}" == "name" ]]; then
        continue
    fi
    sequence_dir="${data_root}/${sequence}"
    if [[ ! -f "${sequence_dir}/seqinfo.ini" ]]; then
        echo "Sequence is incomplete: ${sequence_dir}" >&2
        exit 1
    fi

    echo "Running ${sequence}..."
    "${binary}" \
        --engine "${engine}" \
        --sequence "${sequence_dir}" \
        --output "${output_root}/${sequence}.txt" \
        --score-threshold "${score_threshold}" \
        --nms-threshold "${nms_threshold}" \
        --track-threshold "${track_threshold}" \
        --new-track-threshold "${new_track_threshold}" \
        --match-threshold "${match_threshold}" \
        --track-buffer "${track_buffer}" \
        2>&1 | tee "${report_root}/${sequence}.txt"
    sequence_count=$((sequence_count + 1))
done < "${seqmap}"

if [[ "${sequence_count}" -eq 0 ]]; then
    echo "No sequences were selected by ${seqmap}" >&2
    exit 1
fi

echo "sequences=${sequence_count}"
echo "tracker_results=${output_root}"
