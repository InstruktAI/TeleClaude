#!/usr/bin/env bash
set -euo pipefail

link_shared_scripts() {
    print_header "Linking Shared Scripts"

    local target_dir="$HOME/.teleclaude/scripts"
    mkdir -p "$target_dir"

    local src_build="$INSTALL_DIR/scripts/build_snippet_index.py"
    local src_sync="$INSTALL_DIR/scripts/sync_snippets.py"

    ln -sf "$src_build" "$target_dir/build_snippet_index.py"
    ln -sf "$src_sync" "$target_dir/sync_snippets.py"

    print_success "Shared scripts linked"
}
