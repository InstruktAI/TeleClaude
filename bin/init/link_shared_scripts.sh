#!/usr/bin/env bash
set -euo pipefail

link_shared_scripts() {
    print_header "Linking Shared Scripts"

    local base_dir="$HOME/.teleclaude"
    local target_dir="$base_dir/scripts"
    mkdir -p "$base_dir"
    ln -sfn "$INSTALL_DIR/scripts" "$target_dir"

    # Point ~/.teleclaude/docs at the repo's global docs via a single whole-tree
    # symlink, so every domain, the generated index, and the per-domain
    # domain-baseline.md files are a live view of source that can never be
    # partially deployed. Replace any stale real directory left by older installs.
    local docs_root="$HOME/.teleclaude/docs"
    local source_docs="$INSTALL_DIR/docs/global"
    if [ -d "$source_docs" ]; then
        if [ -e "$docs_root" ] && [ ! -L "$docs_root" ]; then
            rm -rf "$docs_root"
        fi
        ln -sfn "$source_docs" "$docs_root"
    fi

    # Deploy VS Code workspace settings (hide symlinked dirs, prevent symlink traversal)
    local vscode_dir="$base_dir/.vscode"
    local vscode_src="$INSTALL_DIR/teleclaude/install/settings/teleclaude-vscode.json"
    if [ -f "$vscode_src" ]; then
        mkdir -p "$vscode_dir"
        cp "$vscode_src" "$vscode_dir/settings.json"
    fi

    print_success "Shared scripts linked"
}
