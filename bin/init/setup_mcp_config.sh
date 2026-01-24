#!/usr/bin/env bash
set -euo pipefail

setup_mcp_config() {
    print_header "Configuring MCP Integration"

    local mcp_template="$INSTALL_DIR/mcp.json"

    if [ ! -f "$mcp_template" ]; then
        print_warning "MCP template not found: $mcp_template"
        return 0
    fi

    # Read MCP template and substitute INSTALL_DIR placeholder
    local mcp_config
    mcp_config=$(sed "s|{{INSTALL_DIR}}|$INSTALL_DIR|g" "$mcp_template")

    # --- Claude Code (JSON) ---
    local claude_config="$HOME/.claude.json"
    if command -v claude &> /dev/null || [ -f "$claude_config" ]; then
        print_info "Configuring Claude Code..."
        local existing
        existing=$(cat "$claude_config" 2>/dev/null || echo '{}')

        echo "$existing" | jq --argjson mcp "$mcp_config" \
            '.mcpServers.teleclaude = $mcp.mcpServers.teleclaude' > "$claude_config"

        print_success "MCP server added to: $claude_config"
    fi

    # --- Gemini (JSON) ---
    local gemini_dir="$HOME/.gemini"
    local gemini_config="$gemini_dir/settings.json"
    if [ -d "$gemini_dir" ]; then
        print_info "Configuring Gemini..."
        if [ ! -f "$gemini_config" ]; then
            echo '{}' > "$gemini_config"
        fi

        local gemini_existing
        gemini_existing=$(cat "$gemini_config" 2>/dev/null || echo '{}')

        echo "$gemini_existing" | jq --argjson mcp "$mcp_config" \
            '.mcpServers.teleclaude = $mcp.mcpServers.teleclaude' > "$gemini_config"

        print_success "MCP server added to: $gemini_config"
    fi

    # --- Codex (TOML) ---
    local codex_dir="$HOME/.codex"
    local codex_config="$codex_dir/config.toml"
    if [ -d "$codex_dir" ]; then
        print_info "Configuring Codex..."
        if [ ! -f "$codex_config" ]; then
            touch "$codex_config"
        fi

        if ! grep -q "\[mcp_servers.teleclaude\]" "$codex_config"; then
            echo "" >> "$codex_config"
            echo "# TeleClaude MCP Server" >> "$codex_config"
            echo "[mcp_servers.teleclaude]" >> "$codex_config"
            echo "command = \"$INSTALL_DIR/.venv/bin/python\"" >> "$codex_config"
            echo "args = [\"$INSTALL_DIR/bin/mcp-wrapper.py\"]" >> "$codex_config"
            print_success "MCP server appended to: $codex_config"
        else
            print_info "Codex MCP config already present"
        fi
    fi

    print_info "Using mcp-wrapper.py at: $INSTALL_DIR/bin/mcp-wrapper.py"
}
