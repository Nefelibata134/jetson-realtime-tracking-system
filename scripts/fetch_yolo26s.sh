#!/usr/bin/env bash
set -euo pipefail

readonly model_url="https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26s.pt"
readonly model_sha256="646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b"
readonly output_path="${1:-models/yolo26s.pt}"
readonly temporary_path="${output_path}.part.$$"

cleanup() {
    rm -f -- "${temporary_path}"
}
trap cleanup EXIT

mkdir -p "$(dirname "${output_path}")"

if command -v curl >/dev/null 2>&1; then
    curl --fail --location --retry 3 --output "${temporary_path}" "${model_url}"
elif command -v wget >/dev/null 2>&1; then
    wget --tries=3 --output-document="${temporary_path}" "${model_url}"
else
    echo "Model download requires curl or wget." >&2
    exit 1
fi

echo "${model_sha256}  ${temporary_path}" | sha256sum --check --status
mv -- "${temporary_path}" "${output_path}"
echo "Verified ${output_path}"
