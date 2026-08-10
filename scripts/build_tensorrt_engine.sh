#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "Usage: $0 MODEL.onnx OUTPUT.plan [WORKSPACE_MIB]" >&2
    exit 2
fi

readonly onnx_path="$1"
readonly engine_path="$2"
readonly workspace_mib="${3:-2048}"

if [[ ! -f "${onnx_path}" ]]; then
    echo "ONNX model does not exist: ${onnx_path}" >&2
    exit 1
fi

if command -v trtexec >/dev/null 2>&1; then
    trtexec_path="$(command -v trtexec)"
elif [[ -x /usr/src/tensorrt/bin/trtexec ]]; then
    trtexec_path="/usr/src/tensorrt/bin/trtexec"
else
    echo "trtexec was not found." >&2
    exit 1
fi

mkdir -p "$(dirname "${engine_path}")"

echo "trtexec=${trtexec_path}"
echo "onnx=${onnx_path}"
echo "onnx_sha256=$(sha256sum "${onnx_path}" | awk '{print $1}')"
echo "engine=${engine_path}"
echo "precision=fp16"
echo "workspace_mib=${workspace_mib}"

"${trtexec_path}" \
    "--onnx=${onnx_path}" \
    "--saveEngine=${engine_path}" \
    --fp16 \
    "--memPoolSize=workspace:${workspace_mib}"

echo "engine_sha256=$(sha256sum "${engine_path}" | awk '{print $1}')"
