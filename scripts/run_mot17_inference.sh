#!/usr/bin/env bash
set -euo pipefail

engine=""
detector="yolox"
explicit_thresholds=0
explicit_output=0
explicit_report=0
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
  --detector yolox|yolo26 (default: yolox; yolo26 is calibration-only)
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

YOLO26 requires all five thresholds and explicit, unused output/report paths.
Existing output/report directories are never overwritten for either detector.
EOF
}

while [[ $# -gt 0 ]]; do
    if [[ "$1" != -h && "$1" != --help && $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        exit 2
    fi
    case "$1" in
        --engine) engine="$2"; shift 2 ;;
        --detector) detector="$2"; shift 2 ;;
        --data-root) data_root="$2"; shift 2 ;;
        --seqmap) seqmap="$2"; shift 2 ;;
        --output-root) output_root="$2"; explicit_output=1; shift 2 ;;
        --report-root) report_root="$2"; explicit_report=1; shift 2 ;;
        --binary) binary="$2"; shift 2 ;;
        --score-threshold) score_threshold="$2"; explicit_thresholds=$((explicit_thresholds | 1)); shift 2 ;;
        --nms-threshold) nms_threshold="$2"; explicit_thresholds=$((explicit_thresholds | 2)); shift 2 ;;
        --track-threshold) track_threshold="$2"; explicit_thresholds=$((explicit_thresholds | 4)); shift 2 ;;
        --new-track-threshold) new_track_threshold="$2"; explicit_thresholds=$((explicit_thresholds | 8)); shift 2 ;;
        --match-threshold) match_threshold="$2"; explicit_thresholds=$((explicit_thresholds | 16)); shift 2 ;;
        --track-buffer) track_buffer="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

detector_arguments=()
validation_arguments=()
case "$detector" in
    yolox) ;;
    yolo26)
        if [[ $explicit_thresholds != 31 || $explicit_output != 1 || $explicit_report != 1 ]]; then
            echo "YOLO26 requires explicit score/NMS/track/new-track/match thresholds and output/report paths" >&2
            exit 2
        fi
        detector_arguments=(--detector yolo26)
        validation_arguments=(--calibration-only)
        ;;
    *) echo "Unsupported detector: $detector" >&2; exit 2 ;;
esac

# Reject invalid parameters before creating results or loading an engine.
python3 - "$score_threshold" "$nms_threshold" "$track_threshold" \
    "$new_track_threshold" "$match_threshold" "$track_buffer" <<'PY'
import math
import sys

try:
    values = [float(value) for value in sys.argv[1:6]]
    if not all(math.isfinite(value) and 0 <= value <= 1 for value in values):
        raise ValueError("thresholds must be finite and in [0, 1]")
    score, _, track, new_track, _ = values
    if score >= track or new_track < track:
        raise ValueError("require score < track <= new-track")
    if int(sys.argv[6]) <= 0:
        raise ValueError("track-buffer must be positive")
except ValueError as error:
    raise SystemExit(str(error))
PY

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

python3 scripts/validate_mot17.py \
    --train-root "${data_root}" \
    --seqmap "${seqmap}" "${validation_arguments[@]}"

for destination in "$output_root" "$report_root"; do
    if [[ -e "$destination" || -L "$destination" ]]; then
        echo "Refusing to overwrite existing output/report path: $destination" >&2
        exit 1
    fi
done
mkdir -p -- "$(dirname "$output_root")" "$(dirname "$report_root")"
mkdir -- "$output_root" "$report_root"
{
    printf 'schema_version=1\ndetector=%s\n' "$detector"
    printf 'source_commit=%s\n' "$(git rev-parse HEAD)"
    printf 'started_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'candidate_calibration_only=%s\n' "$([[ "$detector" == yolo26 ]] && echo true || echo false)"
    printf 'score=%s\nnms=%s\ntrack=%s\nnew_track=%s\nmatch=%s\ntrack_buffer=%s\n' \
        "$score_threshold" "$nms_threshold" "$track_threshold" \
        "$new_track_threshold" "$match_threshold" "$track_buffer"
    git status --short
    sha256sum -- "$engine" "$binary" "$seqmap" \
        scripts/run_mot17_inference.sh scripts/validate_mot17.py
} > "$report_root/run-contract.txt"
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
    command=("${binary}" "${detector_arguments[@]}" \
        --engine "${engine}" \
        --sequence "${sequence_dir}" \
        --output "${output_root}/${sequence}.txt" \
        --score-threshold "${score_threshold}" \
        --nms-threshold "${nms_threshold}" \
        --track-threshold "${track_threshold}" \
        --new-track-threshold "${new_track_threshold}" \
        --match-threshold "${match_threshold}" \
        --track-buffer "${track_buffer}")
    printf '%q ' "${command[@]}" > "${report_root}/${sequence}.command.sh"
    printf '\n' >> "${report_root}/${sequence}.command.sh"
    "${command[@]}" 2>&1 | tee "${report_root}/${sequence}.txt"
    sequence_count=$((sequence_count + 1))
done < "${seqmap}"

if [[ "${sequence_count}" -eq 0 ]]; then
    echo "No sequences were selected by ${seqmap}" >&2
    exit 1
fi

echo "sequences=${sequence_count}"
echo "tracker_results=${output_root}"
