#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 MODEL_NAME [OUTPUT.pt]" >&2
    exit 2
fi

readonly model_name="$1"
readonly output_path="${2:-models/${model_name}.pt}"
case "${model_name}" in
    yolo26n)
        readonly model_sha256="9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef"
        ;;
    yolo26s)
        readonly model_sha256="646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b"
        ;;
    *)
        echo "Unsupported YOLO26 model: ${model_name}" >&2
        exit 2
        ;;
esac
readonly model_url="https://github.com/ultralytics/assets/releases/download/v8.4.0/${model_name}.pt"
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
