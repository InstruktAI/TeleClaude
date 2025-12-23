#!/usr/bin/env bash
#
# TeleClaude Init Script
# One-time setup: config, service, MCP integration, agent hooks.
# Run 'make install' first to install dependencies.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="${INSTALL_DIR}/install.log"
DAEMON_LOG_FILE="/var/log/instrukt-ai/teleclaude/teleclaude.log"

NON_INTERACTIVE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -y|--yes)
            NON_INTERACTIVE=true
            shift
            ;;
        -h|--help)
            echo "TeleClaude Init"
            echo ""
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  -y, --yes    Non-interactive mode (use defaults)"
            echo "  -h, --help   Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
    log "SUCCESS: $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
    log "ERROR: $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
    log "WARNING: $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
    log "INFO: $1"
}

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
    echo ""
}

# Prompt for input
prompt() {
    local prompt_text="$1"
    local default_value="$2"
    local result

    if [ "$NON_INTERACTIVE" = true ]; then
        echo "$default_value"
        return
    fi

    if [ -n "$default_value" ]; then
        read -p "$prompt_text [$default_value]: " result
        echo "${result:-$default_value}"
    else
        read -p "$prompt_text: " result
        echo "$result"
    fi
}

# Confirm action
confirm() {
    local prompt_text="$1"
    local default="${2:-n}"

    if [ "$NON_INTERACTIVE" = true ]; then
        [ "$default" = "y" ] && return 0 || return 1
    fi

    local response
    read -p "$prompt_text (y/n) [$default]: " response
    response="${response:-$default}"
    [[ "$response" =~ ^[Yy]$ ]]
}

# Detect OS
detect_os() {
    OS_TYPE=$(uname -s)
    case "$OS_TYPE" in
        Linux*)
            OS="linux"
            if [ -f /etc/os-release ]; then
                . /etc/os-release
                DISTRO="$ID"
            else
                DISTRO="unknown"
            fi
            ;;
        Darwin*)
            OS="macos"
            DISTRO="macos"
            ;;
        *)
            print_error "Unsupported OS: $OS_TYPE"
            exit 1
            ;;
    esac
    print_info "Detected OS: $OS ($DISTRO)"
}

# Check prerequisites
check_prerequisites() {
    print_info "Checking prerequisites..."

    if [ ! -d "$INSTALL_DIR/.venv" ]; then
        print_error "Virtual environment not found. Run 'make install' first."
        exit 1
    fi

    if [ ! -f "$INSTALL_DIR/.venv/bin/python" ]; then
        print_error "Python not found in .venv. Run 'make install' first."
        exit 1
    fi

    print_success "Prerequisites OK"
}

# Setup configuration
setup_config() {
    print_header "Configuration Setup"

    # Setup .env
    if [ -f "$INSTALL_DIR/.env" ]; then
        print_warning ".env file already exists"
        if ! confirm "Overwrite existing .env?" "n"; then
            print_info "Keeping existing .env file"
            return 0
        fi
    fi

    # Check templates exist
    if [ ! -f "$INSTALL_DIR/.env.sample" ]; then
        print_error ".env.sample not found"
        exit 1
    fi

    if [ ! -f "$INSTALL_DIR/config.yml.sample" ]; then
        print_error "config.yml.sample not found"
        exit 1
    fi

    # Interactive configuration
    if [ "$NON_INTERACTIVE" = false ]; then
        echo ""
        print_info "Please provide the following information:"
        echo ""

        # Computer name
        DEFAULT_COMPUTER_NAME=$(hostname | cut -d. -f1)
        COMPUTER_NAME=$(prompt "Computer name (shown in session titles)" "$DEFAULT_COMPUTER_NAME")

        # Bot token
        echo ""
        print_info "Get your bot token from @BotFather on Telegram"
        print_info "Visit: https://t.me/botfather"
        BOT_TOKEN=$(prompt "Telegram bot token" "")
        while [ -z "$BOT_TOKEN" ]; do
            print_error "Bot token is required"
            BOT_TOKEN=$(prompt "Telegram bot token" "")
        done

        # User ID
        echo ""
        print_info "Get your Telegram user ID from @userinfobot"
        print_info "Visit: https://t.me/userinfobot"
        USER_ID=$(prompt "Your Telegram user ID" "")
        while [ -z "$USER_ID" ]; do
            print_error "User ID is required"
            USER_ID=$(prompt "Your Telegram user ID" "")
        done

        # Supergroup ID
        echo ""
        print_info "To get supergroup ID:"
        print_info "1. Add your bot to the supergroup"
        print_info "2. Send a message in the group"
        print_info "3. Visit: https://api.telegram.org/bot<TOKEN>/getUpdates"
        print_info "4. Look for 'chat':{id':-1234567890...} (negative number)"
        SUPERGROUP_ID=$(prompt "Telegram supergroup ID (including minus sign)" "")
        while [ -z "$SUPERGROUP_ID" ]; do
            print_error "Supergroup ID is required"
            SUPERGROUP_ID=$(prompt "Telegram supergroup ID" "")
        done

        # Optional: OpenAI API key
        echo ""
        OPENAI_KEY=$(prompt "OpenAI API key (for voice transcription, optional)" "")

    else
        # Non-interactive defaults
        COMPUTER_NAME=$(hostname | cut -d. -f1)
        BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
        USER_ID="${TELEGRAM_USER_ID:-}"
        SUPERGROUP_ID="${TELEGRAM_SUPERGROUP_ID:-}"
        OPENAI_KEY="${OPENAI_API_KEY:-}"

        if [ -z "$BOT_TOKEN" ] || [ -z "$USER_ID" ] || [ -z "$SUPERGROUP_ID" ]; then
            print_error "Non-interactive mode requires environment variables:"
            print_error "  TELEGRAM_BOT_TOKEN"
            print_error "  TELEGRAM_USER_ID"
            print_error "  TELEGRAM_SUPERGROUP_ID"
            exit 1
        fi
    fi

    # Create .env
    cat > "$INSTALL_DIR/.env" <<EOF
# TeleClaude Configuration
# Generated by init.sh on $(date)
WORKING_DIR=${INSTALL_DIR}

# Logging Configuration
TELECLAUDE_LOG_LEVEL=INFO
TELECLAUDE_THIRD_PARTY_LOG_LEVEL=WARNING
TELECLAUDE_THIRD_PARTY_LOGGERS=

# OpenAI API Key (for voice transcription via Whisper)
OPENAI_API_KEY=${OPENAI_KEY}

# Telegram Configuration
TELEGRAM_BOT_TOKEN=${BOT_TOKEN}
TELEGRAM_USER_IDS=${USER_ID}
TELEGRAM_SUPERGROUP_ID=${SUPERGROUP_ID}
EOF

    print_success "Created .env file"

    # Create config.yml if needed
    if [ ! -f "$INSTALL_DIR/config.yml" ]; then
        cp "$INSTALL_DIR/config.yml.sample" "$INSTALL_DIR/config.yml"

        # Update computer name and user in config.yml
        if command -v sed &> /dev/null; then
            sed -i.bak "s/name: .*/name: $COMPUTER_NAME/" "$INSTALL_DIR/config.yml"
            sed -i.bak "s/user: {USER}/user: $USER/" "$INSTALL_DIR/config.yml"
            rm -f "$INSTALL_DIR/config.yml.bak"
        fi

        print_success "Created config.yml"
    else
        print_info "config.yml already exists"
    fi
}

# Setup log file
setup_log_file() {
    print_header "Setting Up Log File"

    print_info "Provisioning canonical log path (sudo may prompt)..."
    local log_file
    local provision_args=("teleclaude" "--print-log-file")
    if [ "$NON_INTERACTIVE" = true ]; then
        provision_args+=("--non-interactive")
    fi

    if ! log_file="$("$INSTALL_DIR/bin/provision-logs.sh" "${provision_args[@]}")"; then
        print_error "Could not provision log file"
        print_info "Re-run init and approve sudo prompts."
        exit 1
    fi

    DAEMON_LOG_FILE="$log_file"
    print_success "Log file ready: $DAEMON_LOG_FILE"
}

# Install systemd service (Linux)
install_systemd_service() {
    local service_name="teleclaude"
    local service_file="/etc/systemd/system/${service_name}.service"
    local path_file="/etc/systemd/system/${service_name}-config.path"

    # Create wrapper script for SSH agent support
    print_info "Creating daemon wrapper script..."
    cat > "$INSTALL_DIR/bin/teleclaude-wrapper.sh" <<'EOF'
#!/bin/bash
# Resolve install dir from this script location so it works under systemd.
INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# Source keychain SSH agent environment
if [ -f ~/.keychain/$(hostname)-sh ]; then
    source ~/.keychain/$(hostname)-sh
fi
# Execute daemon
exec $INSTALL_DIR/.venv/bin/python -m teleclaude.daemon
EOF
    chmod +x "$INSTALL_DIR/bin/teleclaude-wrapper.sh"
    print_success "Created daemon wrapper script"

    # Create service file
    print_info "Creating systemd service..."

    sudo tee "$service_file" > /dev/null <<EOF
[Unit]
Description=TeleClaude Terminal Bridge Daemon
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"
# SSH_AUTH_SOCK sourced from keychain in wrapper
ExecStart=$INSTALL_DIR/bin/teleclaude-wrapper.sh
Restart=on-failure
RestartSec=10
StandardOutput=null
StandardError=null
KillMode=process

[Install]
WantedBy=multi-user.target
EOF

    print_success "Created systemd service file"

    # Create path unit to watch config.yml and restart on changes
    print_info "Creating config watcher..."

    sudo tee "$path_file" > /dev/null <<EOF
[Unit]
Description=TeleClaude Config File Watcher

[Path]
PathModified=$INSTALL_DIR/config.yml
Unit=${service_name}.service

[Install]
WantedBy=multi-user.target
EOF

    print_success "Created config watcher"

    # Reload systemd
    sudo systemctl daemon-reload

    # Enable service and path watcher
    print_info "Enabling service to start on boot..."
    sudo systemctl enable "$service_name"
    sudo systemctl enable "${service_name}-config.path"
    print_success "Service enabled"

    # Start service and path watcher
    print_info "Starting service..."
    sudo systemctl start "$service_name"
    sudo systemctl start "${service_name}-config.path"

    sleep 2

    # Check status
    if sudo systemctl is-active --quiet "$service_name"; then
        print_success "Service started successfully"
        print_info "Service commands:"
        print_info "  Status:  sudo systemctl status $service_name"
        print_info "  Stop:    sudo systemctl stop $service_name"
        print_info "  Restart: sudo systemctl restart $service_name"
        print_info "  Logs:    sudo journalctl -u $service_name -f"
    else
        print_error "Service failed to start"
        print_info "Check logs: sudo journalctl -u $service_name -n 50"
        exit 1
    fi
}

# Install launchd service (macOS)
install_launchd_service() {
    local service_name="ai.instrukt.teleclaude.daemon"
    local plist_file="$HOME/Library/LaunchAgents/${service_name}.plist"
    local template_file="$INSTALL_DIR/config/ai.instrukt.teleclaude.daemon.plist.template"

    # Create LaunchAgents directory if needed
    mkdir -p "$HOME/Library/LaunchAgents"

    # Create plist file from template
    print_info "Creating launchd service from template..."

    if [ ! -f "$template_file" ]; then
        print_error "Template file not found: $template_file"
        exit 1
    fi

    # Detect current PATH to ensure brew and other tools are accessible
    local launchd_path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

    if [ -d "/opt/homebrew/bin" ]; then
        launchd_path="/opt/homebrew/bin:$launchd_path"
    fi
    if [ -d "/usr/local/bin" ]; then
        launchd_path="/usr/local/bin:$launchd_path"
    fi

    # Remove duplicates from PATH
    launchd_path=$(echo "$launchd_path" | tr ':' '\n' | awk '!seen[$0]++' | tr '\n' ':' | sed 's/:$//')

    # Generate plist from template
    sed -e "s|{{PYTHON_PATH}}|$INSTALL_DIR/.venv/bin/python|g" \
        -e "s|{{WORKING_DIR}}|$INSTALL_DIR|g" \
        -e "s|{{PATH}}|$launchd_path|g" \
        "$template_file" > "$plist_file"

    print_success "Created launchd plist file"

    # Load service
    print_info "Loading service..."
    launchctl unload "$plist_file" 2>/dev/null || true
    launchctl load "$plist_file"

    sleep 2

    # Check if running
    if launchctl list | grep -q "$service_name"; then
        print_success "Service loaded successfully"
        print_info "Service commands:"
        print_info "  Status:  launchctl list | grep teleclaude"
        print_info "  Stop:    launchctl unload $plist_file"
        print_info "  Start:   launchctl load $plist_file"
        print_info "  Logs:    tail -f $DAEMON_LOG_FILE"
    else
        print_error "Service failed to load"
        print_info "Check logs: tail -n 50 $DAEMON_LOG_FILE"
        exit 1
    fi
}

# Install service
install_service() {
    print_header "Installing System Service"

    case "$OS" in
        linux)
            install_systemd_service
            ;;
        macos)
            install_launchd_service
            ;;
    esac
}

# Setup MCP integration for all agents
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
            echo "command = \"python3\"" >> "$codex_config"
            echo "args = [\"$INSTALL_DIR/bin/mcp-wrapper.py\"]" >> "$codex_config"
            print_success "MCP server appended to: $codex_config"
        else
            print_info "Codex MCP config already present"
        fi
    fi

    print_info "Using mcp-wrapper.py at: $INSTALL_DIR/bin/mcp-wrapper.py"
}

# Setup agent hooks
setup_agent_hooks() {
    print_header "Configuring Agent Hooks"
    print_info "Running scripts/install_hooks.py..."

    if "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/scripts/install_hooks.py"; then
        print_success "Agent hooks configured"
    else
        print_error "Failed to configure agent hooks"
    fi
}

# Main
main() {
    print_header "TeleClaude Init"
    log "Init started in $INSTALL_DIR"

    detect_os
    check_prerequisites

    setup_config
    setup_log_file
    install_service
    setup_mcp_config
    setup_agent_hooks

    print_header "Init Complete!"

    echo ""
    print_success "TeleClaude has been initialized successfully!"
    echo ""
    print_info "Next steps:"
    echo "  1. Go to your Telegram supergroup"
    echo "  2. Send: /new_session"
    echo "  3. Start sending commands!"
    echo ""
    print_info "The daemon is running as a system service and will:"
    echo "  - Start automatically on boot"
    echo "  - Restart automatically if it crashes"
    echo "  - Log to: $DAEMON_LOG_FILE"
    echo ""
    print_warning "IMPORTANT: Do NOT manually start the daemon!"
    print_warning "The service manages the daemon automatically."
    echo ""

    log "Init completed successfully"
}

main "$@"
