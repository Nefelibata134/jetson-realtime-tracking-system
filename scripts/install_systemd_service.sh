#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: sudo $0 --binary PATH --engine PATH" >&2
}

binary=""
engine=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --binary)
      binary="${2:-}"
      shift 2
      ;;
    --engine)
      engine="${2:-}"
      shift 2
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

[[ $EUID -eq 0 ]] || {
  echo "run this installer with sudo" >&2
  exit 1
}

missing_commands=()
for command in systemctl python3 logrotate stdbuf; do
  if ! command -v "$command" >/dev/null 2>&1; then
    missing_commands+=("$command")
  fi
done
if [[ ${#missing_commands[@]} -ne 0 ]]; then
  echo "missing required commands: ${missing_commands[*]}" >&2
  echo "Ubuntu: apt-get install -y python3 logrotate coreutils" >&2
  exit 1
fi

[[ -x $binary && -f $engine ]] || {
  usage
  exit 2
}

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! getent group edge-vision >/dev/null; then
  groupadd --system edge-vision
fi
if ! id edge-vision >/dev/null 2>&1; then
  useradd \
    --system \
    --gid edge-vision \
    --home-dir /var/lib/edge-vision \
    --shell /usr/sbin/nologin \
    edge-vision
fi
for group in video render; do
  if getent group "$group" >/dev/null; then
    usermod -a -G "$group" edge-vision
  fi
done

install -d -m 0755 /opt/edge-vision/bin
install -d -o edge-vision -g edge-vision -m 0750 \
  /var/lib/edge-vision/models \
  /var/lib/edge-vision/spool \
  /var/lib/edge-vision/metrics \
  /var/log/edge-vision
install -d -m 0755 /etc/edge-vision

install -m 0755 "$binary" \
  /opt/edge-vision/bin/edge_vision_realtime_detect
install -m 0755 "$project_root/scripts/run_edge_vision_service.sh" \
  /opt/edge-vision/bin/run-edge-vision
install -m 0755 "$project_root/scripts/prune_event_spool.py" \
  /opt/edge-vision/bin/prune-event-spool
install -o edge-vision -g edge-vision -m 0640 "$engine" \
  /var/lib/edge-vision/models/yolox_nano_fp16.plan

if [[ ! -f /etc/edge-vision/edge-vision.env ]]; then
  install -m 0640 \
    "$project_root/deploy/systemd/edge-vision.env.example" \
    /etc/edge-vision/edge-vision.env
fi
install -m 0644 "$project_root/deploy/systemd/edge-vision.service" \
  /etc/systemd/system/edge-vision.service
install -m 0644 "$project_root/deploy/systemd/edge-vision-prune.service" \
  /etc/systemd/system/edge-vision-prune.service
install -m 0644 "$project_root/deploy/systemd/edge-vision-prune.timer" \
  /etc/systemd/system/edge-vision-prune.timer
install -m 0644 "$project_root/deploy/systemd/edge-vision.logrotate" \
  /etc/logrotate.d/edge-vision

systemctl daemon-reload
systemctl enable edge-vision.service edge-vision-prune.timer

echo "installed edge-vision service"
echo "configuration: /etc/edge-vision/edge-vision.env"
echo "start: systemctl start edge-vision.service"
