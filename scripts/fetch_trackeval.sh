#!/usr/bin/env bash
set -euo pipefail

readonly repository_url="https://github.com/JonathonLuiten/TrackEval.git"
readonly pinned_commit="12c8791b303e0a0b50f753af204249e622d0281a"
target="${1:-external/TrackEval}"

if [[ -e "${target}" && ! -d "${target}/.git" ]]; then
    echo "Target exists but is not a Git repository: ${target}" >&2
    exit 1
fi

if [[ ! -d "${target}/.git" ]]; then
    mkdir -p "$(dirname "${target}")"
    git clone --filter=blob:none "${repository_url}" "${target}"
fi

if [[ -n "$(git -C "${target}" status --short)" ]]; then
    echo "TrackEval checkout contains local changes: ${target}" >&2
    exit 1
fi

git -C "${target}" fetch --depth 1 origin "${pinned_commit}"
git -C "${target}" checkout --detach "${pinned_commit}"

actual_commit="$(git -C "${target}" rev-parse HEAD)"
if [[ "${actual_commit}" != "${pinned_commit}" ]]; then
    echo "TrackEval commit verification failed" >&2
    exit 1
fi

echo "TrackEval commit: ${actual_commit}"
echo "TrackEval root: ${target}"
