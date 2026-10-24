#!/usr/bin/env bash
# Ask the installed controller for the recorded purpose of one checkout.

set -euo pipefail

if [ "$#" -ne 2 ] || { [ "$1" != "--purpose" ] && [ "$1" != "--home" ]; }; then
    printf 'Usage: %s --purpose|--home <checkout-path>\n' "$0" >&2
    exit 2
fi

telec_link="$HOME/.local/bin/telec"
if [ ! -L "$telec_link" ]; then
    if [ "$1" = "--home" ]; then
        printf 'No installed checkout can supply a development home.\n' >&2
        exit 1
    fi
    printf 'unassociated\n'
    exit 0
fi

telec_target="$(readlink "$telec_link")"
case "$telec_target" in
    /*) ;;
    *) telec_target="$HOME/.local/bin/$telec_target" ;;
esac
installed_root="$(cd "$(dirname "$telec_target")/.." && pwd)"
installed_python="$installed_root/.venv/bin/python"
if [ ! -x "$installed_python" ]; then
    printf 'The installed checkout has no usable Python environment: %s\n' "$installed_python" >&2
    exit 1
fi

(cd "$HOME" && env "PYTHONPATH=$installed_root" "$installed_python" -P -m teleclaude.entrypoints.development_checkout "$1" "$2")
