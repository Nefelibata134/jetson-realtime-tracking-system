#!/usr/bin/env bash
set -euo pipefail

readonly url="https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.pth"
readonly digest="9de513de589ac98bb92d3bca53b5af7b9acfa9b0bacb831f7999d0f7afaee8f0"
readonly destination="${1:-models/yolox_tiny.pth}"
if [[ -e "$destination" || -L "$destination" ]]; then
    printf '%s  %s\n' "$digest" "$destination" | sha256sum --check
    exit 0
fi
mkdir -p "$(dirname "$destination")"
temporary="$(mktemp "$(dirname "$destination")/.tiny-weight.XXXXXXXX")"
trap 'rm -f -- "$temporary"' EXIT
curl --fail --location --retry 3 --output "$temporary" "$url"
printf '%s  %s\n' "$digest" "$temporary" | sha256sum --check
# Exclusive creation avoids replacing an existing asset, including a symlink.
(set -o noclobber; cat "$temporary" > "$destination")
printf 'Verified %s\n' "$destination"
