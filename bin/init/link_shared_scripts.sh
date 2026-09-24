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

    # Deploy VS Code workspace settings (hide symlinked dirs, prevent symlink traversal)
    local vscode_dir="$base_dir/.vscode"
    local vscode_src="$INSTALL_DIR/teleclaude/install/settings/teleclaude-vscode.json"
    if [ -f "$vscode_src" ]; then
        mkdir -p "$vscode_dir"
        cp "$vscode_src" "$vscode_dir/settings.json"
    fi

    print_success "Shared scripts linked"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    TELECLAUDE_HOME="${TELECLAUDE_HOME:-$HOME/.teleclaude}"
    link_shared_scripts
fi
