#!/usr/bin/env bash
set -euo pipefail

trackeval_root="external/TrackEval"
python_binary="python3"
gt_root="data/mot17/train"
tracker_root="outputs/mot17"
tracker_name="edge_vision"
seqmap="configs/mot17/holdout.txt"
output_root="reports/mot17/trackeval"

usage() {
    cat <<'EOF'
Usage:
  scripts/run_trackeval_mot17.sh [options]

Options:
  --trackeval-root PATH
  --python PATH
  --gt-root PATH
  --tracker-root PATH
  --tracker-name NAME
  --seqmap PATH
  --output-root PATH
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --trackeval-root) trackeval_root="$2"; shift 2 ;;
        --python) python_binary="$2"; shift 2 ;;
        --gt-root) gt_root="$2"; shift 2 ;;
        --tracker-root) tracker_root="$2"; shift 2 ;;
        --tracker-name) tracker_name="$2"; shift 2 ;;
        --seqmap) seqmap="$2"; shift 2 ;;
        --output-root) output_root="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

runner="${trackeval_root}/scripts/run_mot_challenge.py"
if [[ ! -f "${runner}" ]]; then
    echo "TrackEval runner does not exist: ${runner}" >&2
    exit 1
fi
for path in "${gt_root}" "${tracker_root}/${tracker_name}/data"; do
    if [[ ! -d "${path}" ]]; then
        echo "Required directory does not exist: ${path}" >&2
        exit 1
    fi
done
if [[ ! -f "${seqmap}" ]]; then
    echo "Sequence map does not exist: ${seqmap}" >&2
    exit 1
fi

"${python_binary}" - <<'PY'
import numpy as np
import scipy  # noqa: F401

if "float" not in np.__dict__ or "int" not in np.__dict__:
    raise SystemExit(
        "The pinned TrackEval revision requires NumPy < 1.24. "
        "On Ubuntu 22.04 install python3-numpy and python3-scipy from apt."
    )
PY
seqmap_root="${gt_root}/seqmaps"
trackeval_seqmap="${seqmap_root}/MOT17-train.txt"
trackeval_output="${tracker_root}/${tracker_name}"
mkdir -p "${output_root}" "${seqmap_root}"
cp -- "${seqmap}" "${trackeval_seqmap}"
rm -f \
    "${trackeval_output}/pedestrian_summary.txt" \
    "${trackeval_output}/pedestrian_detailed.csv"

"${python_binary}" "${runner}" \
    --GT_FOLDER "${gt_root}" \
    --TRACKERS_FOLDER "${tracker_root}" \
    --TRACKERS_TO_EVAL "${tracker_name}" \
    --BENCHMARK MOT17 \
    --SPLIT_TO_EVAL train \
    --METRICS HOTA CLEAR Identity \
    --SKIP_SPLIT_FOL True \
    --DO_PREPROC True \
    --PLOT_CURVES False \
    --PRINT_CONFIG False

trackeval_summary="${trackeval_output}/pedestrian_summary.txt"
if [[ ! -f "${trackeval_summary}" ]]; then
    echo "TrackEval did not create the expected summary: ${trackeval_summary}" >&2
    exit 1
fi

published_output="${output_root}/${tracker_name}"
mkdir -p "${published_output}"
cp -- "${trackeval_summary}" "${published_output}/pedestrian_summary.txt"
if [[ -f "${trackeval_output}/pedestrian_detailed.csv" ]]; then
    cp -- \
        "${trackeval_output}/pedestrian_detailed.csv" \
        "${published_output}/pedestrian_detailed.csv"
fi

echo "summary=${published_output}/pedestrian_summary.txt"
