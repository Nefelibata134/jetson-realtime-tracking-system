#!/usr/bin/env bash
set -euo pipefail

exec "$(dirname "${BASH_SOURCE[0]}")/fetch_yolo26.sh" yolo26n "${1:-models/yolo26n.pt}"
