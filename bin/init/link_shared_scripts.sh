#!/usr/bin/env bash
set -euo pipefail

if ! declare -F print_header >/dev/null; then
    print_header() {
        printf '\n%s\n\n' "$1"
    }
fi

if ! declare -F print_success >/dev/null; then
    print_success() {
        printf '✓ %s\n' "$1"
    }
fi

link_shared_scripts() {
    print_header "Linking Shared Scripts"

    local base_dir="${TELECLAUDE_HOME:-$HOME/.teleclaude}"
    local target_dir="$base_dir/scripts"
    mkdir -p "$base_dir"
    ln -sfn "$INSTALL_DIR/scripts" "$target_dir"

    print_success "Shared scripts linked"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    TELECLAUDE_HOME="${TELECLAUDE_HOME:-$HOME/.teleclaude}"
    link_shared_scripts
fi
