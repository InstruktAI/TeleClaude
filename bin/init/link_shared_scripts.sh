#!/usr/bin/env bash
set -euo pipefail

link_shared_scripts() {
    print_header "Linking Shared Scripts"

    local base_dir="$HOME/.teleclaude"
    local target_dir="$base_dir/scripts"
    mkdir -p "$base_dir"
    ln -sfn "$INSTALL_DIR/scripts" "$target_dir"

    # Ensure ~/.teleclaude/docs entries point at repo global docs, without
    # deleting the docs root (preserve user-maintained third-party docs).
    local docs_root="$HOME/.teleclaude/docs"
    local source_docs="$INSTALL_DIR/docs/global"
    mkdir -p "$docs_root"
    if [ -d "$source_docs" ]; then
        local entry src_path dst_path
        for src_path in "$source_docs"/*; do
            entry="$(basename "$src_path")"
            dst_path="$docs_root/$entry"
            [ "${entry#*.}" != "$entry" ] && continue

            if [ -L "$dst_path" ]; then
                rm -f "$dst_path"
            elif [ -d "$dst_path" ]; then
                [ "$entry" = "third-party" ] && continue
                rm -rf "$dst_path"
            elif [ -f "$dst_path" ]; then
                rm -f "$dst_path"
            fi

            if [ -d "$src_path" ] || [ "$entry" = "baseline.md" ] || [ "$entry" = "index.yaml" ]; then
                ln -s "$src_path" "$dst_path"
            fi
        done
    fi

    print_success "Shared scripts linked"
}
