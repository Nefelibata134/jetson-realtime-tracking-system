#!/usr/bin/env bash
set -euo pipefail

readonly model_url="https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx"
readonly model_sha256="c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d"
readonly output_path="${1:-models/yolox_nano.onnx}"

mkdir -p "$(dirname "${output_path}")"
curl --fail --location --retry 3 --output "${output_path}" "${model_url}"
echo "${model_sha256}  ${output_path}" | sha256sum --check --status
echo "Verified ${output_path}"
