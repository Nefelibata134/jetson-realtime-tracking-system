#!/usr/bin/env bash
set -euo pipefail

exec "$(dirname "${BASH_SOURCE[0]}")/fetch_yolo26.sh" yolo26s "${1:-models/yolo26s.pt}"
