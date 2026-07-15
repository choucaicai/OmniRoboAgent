#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_assets="${1:-/home/zzz/vla_code/robocasa/robocasa/models/assets}"
target_assets="${2:-${repo_root}/benchmarks/RoboCasa/robocasa/models/assets}"

if [[ ! -d "${source_assets}" ]]; then
    echo "RoboCasa assets source does not exist: ${source_assets}" >&2
    exit 1
fi
if [[ ! -d "${target_assets}" ]]; then
    echo "RoboCasa submodule assets directory does not exist: ${target_assets}" >&2
    exit 1
fi

source_assets="$(cd "${source_assets}" && pwd)"
target_assets="$(cd "${target_assets}" && pwd)"
if [[ "${source_assets}" == "${target_assets}" ]]; then
    echo "Source and target assets directories must differ" >&2
    exit 1
fi

for source_entry in "${source_assets}"/*; do
    [[ -d "${source_entry}" ]] || continue
    name="$(basename "${source_entry}")"
    target_entry="${target_assets}/${name}"
    if [[ -L "${target_entry}" ]]; then
        expected_target="$(readlink -f "${source_entry}")"
        current_target="$(readlink -f "${target_entry}" || true)"
        if [[ "${current_target}" == "${expected_target}" ]]; then
            continue
        fi
        echo "Refusing link with unexpected target: ${target_entry}" >&2
        exit 1
    fi
    if [[ ! -e "${target_entry}" ]]; then
        ln -s "${source_entry}" "${target_entry}"
        continue
    fi
    if [[ ! -d "${target_entry}" ]]; then
        echo "Refusing to replace existing asset path: ${target_entry}" >&2
        exit 1
    fi
    cp -as --no-clobber "${source_entry}/." "${target_entry}/"
done

echo "RoboCasa assets linked from ${source_assets}"
