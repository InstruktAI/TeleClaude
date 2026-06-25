#!/usr/bin/env bash
set -euo pipefail

link_shared_scripts() {
    print_header "Linking Shared Scripts"

    local base_dir="${TELECLAUDE_HOME:-$HOME/.teleclaude}"
    local target_dir="$base_dir/scripts"
    mkdir -p "$base_dir"
    ln -sfn "$INSTALL_DIR/scripts" "$target_dir"

    # Bootstrap the runtime docs root as a whole-tree symlink onto the repo's
    # global docs (a mother-only initial view). The first `telec sync` replaces
    # it with a per-file composition of every publisher's docs/global, a merged
    # index, and per-domain domain-baseline-bundle.md files. Replace any stale
    # real directory left by older installs.
    local docs_root="$base_dir/docs"
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
