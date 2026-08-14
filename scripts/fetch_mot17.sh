#!/usr/bin/env bash
set -euo pipefail

readonly dataset_url="https://motchallenge.net/data/MOT17.zip"
dataset_root="${1:-data/mot17}"
archive="${2:-data/archives/MOT17.zip}"
sentinel="${dataset_root}/train/MOT17-02-FRCNN/seqinfo.ini"

if [[ -f "${sentinel}" ]] && \
    python3 scripts/validate_mot17.py \
        --train-root "${dataset_root}/train" \
        --seqmap configs/mot17/calibration.txt && \
    python3 scripts/validate_mot17.py \
        --train-root "${dataset_root}/train" \
        --seqmap configs/mot17/holdout.txt; then
    echo "MOT17 is already available: ${dataset_root}"
    exit 0
fi

for command in wget unzip; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        echo "Required command was not found: ${command}" >&2
        exit 1
    fi
done

mkdir -p "$(dirname "${archive}")" "${dataset_root}"
wget --continue "${dataset_url}" --output-document "${archive}"
unzip -q "${archive}" -d "${dataset_root}"

if [[ ! -f "${sentinel}" ]]; then
    echo "MOT17 extraction did not produce the expected directory layout" >&2
    exit 1
fi

python3 scripts/validate_mot17.py \
    --train-root "${dataset_root}/train" \
    --seqmap configs/mot17/calibration.txt
python3 scripts/validate_mot17.py \
    --train-root "${dataset_root}/train" \
    --seqmap configs/mot17/holdout.txt

echo "MOT17 root: ${dataset_root}"
echo "Archive retained at: ${archive}"
