#!/usr/bin/env bash
set -euo pipefail

link_shared_scripts() {
    print_header "Linking Shared Scripts"

    local base_dir="$HOME/.teleclaude"
    local target_dir="$base_dir/scripts"
    mkdir -p "$base_dir"
    ln -sfn "$INSTALL_DIR/scripts" "$target_dir"

    # Ensure global docs path points at repo global docs.
    local docs_link="$HOME/.teleclaude/docs"
    rm -rf "$docs_link"
    ln -s "$INSTALL_DIR/docs/global" "$docs_link"

    print_success "Shared scripts linked"
}
