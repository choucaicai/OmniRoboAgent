#!/usr/bin/env bash
set -euo pipefail

display_id="${DISPLAY_ID:-1}"
conda_env="${CONDA_ENV:-omniagent-eb}"
config="${1:-configs/runs/eb_alfred_smoke.yaml}"
display=":${display_id}"
xvfb_pid=""

cleanup() {
    if [[ -n "${xvfb_pid}" ]]; then
        kill "${xvfb_pid}" 2>/dev/null || true
        wait "${xvfb_pid}" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

if ! DISPLAY="${display}" xdpyinfo >/dev/null 2>&1; then
    Xvfb "${display}" \
        -screen 0 1024x768x24 \
        -ac \
        +extension GLX \
        +render \
        -noreset \
        -nolisten tcp &
    xvfb_pid=$!

    for _ in {1..50}; do
        if DISPLAY="${display}" xdpyinfo >/dev/null 2>&1; then
            break
        fi
        sleep 0.1
    done
fi

if ! DISPLAY="${display}" xdpyinfo >/dev/null 2>&1; then
    echo "Xvfb did not become ready on ${display}" >&2
    exit 1
fi

export DISPLAY="${display}"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"
export no_proxy="${no_proxy:-127.0.0.1,localhost}"

conda run --no-capture-output -n "${conda_env}" \
    omniroboagent run --config "${config}"
