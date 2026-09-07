#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 3 ]]; then
    echo "Usage: $0 TINY640.onnx NEW_RESULT_DIRECTORY TRT_PROBE_BINARY" >&2
    exit 2
fi
readonly onnx_path="$1"
readonly run_dir="$2"
readonly probe="$3"
readonly expected="d19526fb64f78d0dd58c2cf0b4fa283a895356d45bc8c91068233b4295020014"
readonly script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ "$(uname -m)" == aarch64 ]] || { echo "Target Jetson required" >&2; exit 1; }
grep -aq 'nvidia,p3767-0003' /proc/device-tree/compatible || exit 1
[[ "$(nvpmodel -q)" == $'NV Power Mode: 25W\n1' ]] || { echo "25W required; mode is not changed" >&2; exit 1; }
[[ "$(systemctl show edge-vision.service -p ActiveState --value)" == inactive ]] || {
    echo "Stop the service in a recovery-protected window before engine construction" >&2; exit 1;
}
[[ -x "$probe" ]] || { echo "TensorRT probe binary is required" >&2; exit 1; }
[[ ! -e "$run_dir" && ! -L "$run_dir" ]] || { echo "Refusing to reuse result directory" >&2; exit 1; }
printf '%s  %s\n' "$expected" "$onnx_path" | sha256sum --check
mkdir -p "$run_dir"
exec > >(tee "$run_dir/validation.log") 2>&1
trap 'result=$?; printf "exit_code=%s\n" "$result" > "$run_dir/exit-code.txt"' EXIT
printf 'started_utc=%s\n' "$(date -u +%FT%TZ)"
uname -a
cat /etc/nv_tegra_release
dpkg-query -W nvidia-jetpack nvidia-l4t-core libnvinfer10 libnvonnxparsers10
nvpmodel -q
for clock_file in /sys/devices/system/cpu/cpufreq/policy*/scaling_{governor,min_freq,max_freq} \
                  /sys/class/devfreq/17000000.gpu/{governor,min_freq,max_freq}; do
    printf '%s=' "$clock_file"
    cat "$clock_file"
done
plan="$run_dir/yolox_tiny_640_fp16.plan"
printf 'build_command='; printf '%q ' bash "$script_dir/build_tensorrt_engine.sh" "$onnx_path" "$plan" 2048; printf '\n'
bash "$script_dir/build_tensorrt_engine.sh" "$onnx_path" "$plan" 2048
[[ -s "$plan" ]] || exit 1
sha256sum "$onnx_path" "$plan" "$probe"
printf 'probe_command='; printf '%q ' "$probe" "$plan"; printf '\n'
"$probe" "$plan" | tee "$run_dir/probe.log"
grep -F 'input=images shape=1x3x640x640' "$run_dir/probe.log"
grep -F 'output=output shape=1x8400x85' "$run_dir/probe.log"
grep -F 'finite=714000/714000' "$run_dir/probe.log"
printf 'engine_contract=PASS\nquality_and_realtime_acceptance=not_evaluated\n'
