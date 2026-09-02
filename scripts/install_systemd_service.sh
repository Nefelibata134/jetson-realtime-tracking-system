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
for command in systemctl python3 logrotate stdbuf grep sed; do
  if ! command -v "$command" >/dev/null 2>&1; then
    missing_commands+=("$command")
  fi
done
if [[ ${#missing_commands[@]} -ne 0 ]]; then
  echo "missing required commands: ${missing_commands[*]}" >&2
  echo "Ubuntu: apt-get install -y python3 logrotate coreutils grep sed" >&2
  exit 1
fi

[[ -x $binary && -f $engine ]] || {
  usage
  exit 2
}

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
engine_filename="$(basename -- "$engine")"
if [[ ! $engine_filename =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "engine filename contains unsupported characters: $engine_filename" >&2
  exit 2
fi
installed_engine="/var/lib/edge-vision/models/$engine_filename"

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
  "$installed_engine"

env_path="/etc/edge-vision/edge-vision.env"
if [[ ! -f $env_path ]]; then
  install -m 0640 \
    "$project_root/deploy/systemd/edge-vision.env.example" \
    "$env_path"
fi
if grep -q '^EDGE_VISION_ENGINE=' "$env_path"; then
  sed -i \
    "s|^EDGE_VISION_ENGINE=.*$|EDGE_VISION_ENGINE=$installed_engine|" \
    "$env_path"
else
  printf '\nEDGE_VISION_ENGINE=%s\n' "$installed_engine" >>"$env_path"
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
echo "engine: $installed_engine"
echo "start: systemctl start edge-vision.service"
