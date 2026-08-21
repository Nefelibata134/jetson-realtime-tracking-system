#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: sudo bash scripts/finalize_service_soak.sh --run-dir DIRECTORY [--service NAME]" >&2
}

run_dir=""
service="edge-vision.service"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --run-dir) run_dir="$2"; shift 2 ;;
        --service) service="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

[[ ${EUID} -eq 0 ]] || { echo "run this script with sudo" >&2; exit 1; }
[[ -n "${run_dir}" && -d "${run_dir}" ]] || {
    echo "soak run directory does not exist: ${run_dir}" >&2
    exit 1
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
metrics_path="/var/lib/edge-vision/metrics/latest.json"
was_active=false
if systemctl is-active --quiet "${service}"; then
    was_active=true
fi
[[ "${was_active}" == true ]] || {
    echo "service must be active before finalizing a soak run" >&2
    exit 1
}

restart_service() {
    if [[ "${was_active}" == true ]] && ! systemctl is-active --quiet "${service}"; then
        systemctl start "${service}" || true
    fi
}
trap restart_service EXIT

systemctl stop "${service}"
[[ -s "${metrics_path}" ]] || {
    echo "final runtime metrics were not published: ${metrics_path}" >&2
    exit 1
}
install -m 0644 "${metrics_path}" "${run_dir}/final_metrics.json"

if [[ "${was_active}" == true ]]; then
    systemctl start "${service}"
    ready=false
    for _ in $(seq 1 60); do
        state="$(systemctl show "${service}" -p ActiveState -p SubState -p StatusText)"
        if grep -q '^ActiveState=active$' <<<"${state}" &&
           grep -q '^SubState=running$' <<<"${state}" &&
           grep -q '^StatusText=video analytics runtime is ready$' <<<"${state}"; then
            ready=true
            break
        fi
        sleep 1
    done
    [[ "${ready}" == true ]] || {
        echo "service did not return to ready state" >&2
        exit 1
    }
fi

python3 "${script_dir}/summarize_service_soak.py" --run-dir "${run_dir}"

if [[ -n "${SUDO_UID:-}" && -n "${SUDO_GID:-}" ]]; then
    chown -R "${SUDO_UID}:${SUDO_GID}" "${run_dir}"
fi

trap - EXIT
echo "service_restarted=${was_active}"
echo "run_directory=${run_dir}"
