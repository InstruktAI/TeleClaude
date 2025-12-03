#!/usr/bin/env bash
#
# TeleClaude Installation Script
# Installs dependencies, creates service, and configures TeleClaude daemon
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Installation directory (where script is located)
INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="${INSTALL_DIR}/install.log"

# Configuration
PYTHON_MIN_VERSION="3.11"
TMUX_MIN_VERSION="3.0"
NON_INTERACTIVE=false
DAEMON_LOG_FILE="/var/log/teleclaude.log"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -y|--yes)
            NON_INTERACTIVE=true
            shift
            ;;
        -h|--help)
            echo "TeleClaude Installer"
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

# Print functions
print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
    echo ""
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

# Check Python version
check_python() {
    print_info "Checking Python version..."

    # Try python3, python3.11, python3.12, etc.
    for cmd in python3.12 python3.11 python3; do
        if command -v "$cmd" &> /dev/null; then
            PYTHON_CMD="$cmd"
            PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')

            # Compare versions
            if [ "$(printf '%s\n' "$PYTHON_MIN_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" = "$PYTHON_MIN_VERSION" ]; then
                print_success "Found Python $PYTHON_VERSION at $(command -v $cmd)"
                return 0
            fi
        fi
    done

    print_error "Python $PYTHON_MIN_VERSION or higher not found"
    print_info "Please install Python $PYTHON_MIN_VERSION+ first"
    exit 1
}

# Check Node.js (required for Claude Code)
check_node() {
    print_info "Checking Node.js..."

    if ! command -v node &> /dev/null; then
        print_error "Node.js not found"
        print_info "Node.js is required for Claude Code"
        print_info ""
        print_info "Install Node.js:"
        print_info "  macOS:  brew install node"
        print_info "  Ubuntu: sudo apt install nodejs npm"
        print_info "  Fedora: sudo dnf install nodejs npm"
        print_info ""
        print_info "Or visit: https://nodejs.org/"
        exit 1
    fi

    if ! command -v npm &> /dev/null; then
        print_error "npm not found"
        print_info "npm is required for installing Claude Code"
        exit 1
    fi

    NODE_VERSION=$(node --version 2>&1)
    NPM_VERSION=$(npm --version 2>&1)
    print_success "Found Node.js $NODE_VERSION and npm $NPM_VERSION"
}

# Install system dependencies
install_system_deps() {
    print_header "Installing System Dependencies"

    # Check and install tmux
    if command -v tmux &> /dev/null; then
        TMUX_VERSION=$(tmux -V | awk '{print $2}')
        print_success "tmux $TMUX_VERSION already installed"
    else
        print_info "Installing tmux..."
        install_package tmux
    fi

    # Check and install ffmpeg (for voice transcription)
    if command -v ffmpeg &> /dev/null; then
        print_success "ffmpeg already installed"
    else
        print_info "Installing ffmpeg..."
        install_package ffmpeg
    fi

    # Check and install jq (for JSON manipulation)
    if command -v jq &> /dev/null; then
        print_success "jq already installed"
    else
        print_info "Installing jq..."
        install_package jq
    fi

    # Check and install socat (for MCP socket bridge)
    if command -v socat &> /dev/null; then
        print_success "socat already installed"
    else
        print_info "Installing socat..."
        install_package socat
    fi

    # Install Claude Code
    install_claude_code
}

# Install package based on OS
install_package() {
    local package="$1"

    case "$DISTRO" in
        ubuntu|debian)
            sudo apt-get update -qq
            sudo apt-get install -y "$package"
            ;;
        fedora|rhel|centos)
            sudo dnf install -y "$package"
            ;;
        arch|manjaro)
            sudo pacman -S --noconfirm "$package"
            ;;
        macos)
            if ! command -v brew &> /dev/null; then
                print_error "Homebrew not found. Please install from https://brew.sh"
                exit 1
            fi
            brew install "$package"
            ;;
        *)
            print_error "Unsupported distro: $DISTRO"
            print_info "Please install $package manually"
            exit 1
            ;;
    esac

    print_success "Installed $package"
}

# Setup Python virtual environment
setup_venv() {
    print_header "Setting Up Python Virtual Environment"

    if [ -d "$INSTALL_DIR/.venv" ]; then
        print_warning "Virtual environment already exists"
        if confirm "Recreate virtual environment?" "n"; then
            rm -rf "$INSTALL_DIR/.venv"
        else
            print_info "Using existing virtual environment"
            return 0
        fi
    fi

    print_info "Creating virtual environment..."
    "$PYTHON_CMD" -m venv "$INSTALL_DIR/.venv"
    print_success "Virtual environment created"

    print_info "Upgrading pip..."
    "$INSTALL_DIR/.venv/bin/pip" install --upgrade pip -q

    print_info "Installing Python dependencies..."
    "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q

    print_info "Installing TeleClaude package..."
    "$INSTALL_DIR/.venv/bin/pip" install -e "$INSTALL_DIR" -q
    print_success "Python dependencies and package installed"
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

    # Copy templates
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
# Generated by install.sh on $(date)
WORKING_DIR=${INSTALL_DIR}

# Logging Configuration
TELECLAUDE_LOG_LEVEL=INFO
TELECLAUDE_LOG_FILE=${DAEMON_LOG_FILE}

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

    local log_file="$DAEMON_LOG_FILE"

    while true; do
        if [ -f "$log_file" ]; then
            print_success "Log file already exists: $log_file"
            break
        fi

        print_info "Creating log file: $log_file"
        if sudo touch "$log_file" 2>/dev/null && sudo chown "$USER" "$log_file" 2>/dev/null && sudo chmod 644 "$log_file" 2>/dev/null; then
            print_success "Log file created and owned by $USER"
            break
        else
            print_error "Could not create log file at $log_file"
            print_info "Try a path you have write access to"
            log_file=$(prompt "Log file path" "${INSTALL_DIR}/teleclaude.log")
        fi
    done

    # Update .env with the working path
    if [ "$log_file" != "$DAEMON_LOG_FILE" ]; then
        sed -i.bak "s|TELECLAUDE_LOG_FILE=.*|TELECLAUDE_LOG_FILE=$log_file|" "$INSTALL_DIR/.env"
        rm -f "$INSTALL_DIR/.env.bak"
        print_info "Updated .env with new log path"
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

# Install systemd service (Linux)
install_systemd_service() {
    local service_name="teleclaude"
    local service_file="/etc/systemd/system/${service_name}.service"

    # Create wrapper script for SSH agent support
    print_info "Creating daemon wrapper script..."
    cat > "$INSTALL_DIR/bin/teleclaude-wrapper.sh" <<'EOF'
#!/bin/bash
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

    # Reload systemd
    sudo systemctl daemon-reload

    # Enable service
    print_info "Enabling service to start on boot..."
    sudo systemctl enable "$service_name"
    print_success "Service enabled"

    # Start service
    print_info "Starting service..."
    sudo systemctl start "$service_name"

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
    # Priority: /opt/homebrew/bin (M1/ARM Macs), /usr/local/bin (Intel Macs), system paths
    local launchd_path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

    # Add brew paths if they exist
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

# Install Claude Code
install_claude_code() {
    print_header "Installing Claude Code"

    if command -v claude &> /dev/null; then
        CLAUDE_VERSION=$(claude --version 2>&1 || echo "unknown")
        print_warning "Claude Code already installed ($CLAUDE_VERSION)"
        if ! confirm "Reinstall Claude Code?" "n"; then
            return 0
        fi
    fi

    print_info "Installing Claude Code globally via npm..."
    if npm install -g @anthropic-ai/claude-code &> "$LOG_FILE"; then
        print_success "Claude Code installed successfully"
        print_info "Note: You may need to restart your shell for 'claude' command to be available"
    else
        print_error "Failed to install Claude Code"
        print_info "Check log: $LOG_FILE"
        print_warning "You can install manually: npm install -g @anthropic-ai/claude-code"
        # Don't exit - not critical for TeleClaude
    fi
}

# Setup Claude Code MCP integration
setup_mcp_config() {
    print_header "Configuring Claude Code MCP Integration"

    local claude_config="$HOME/.claude.json"
    local mcp_template="$INSTALL_DIR/mcp.json"

    if [ ! -f "$mcp_template" ]; then
        print_warning "MCP template not found: $mcp_template"
        return 0
    fi

    # Read existing config or empty object
    local existing
    existing=$(cat "$claude_config" 2>/dev/null || echo '{}')

    # Read MCP template and substitute INSTALL_DIR placeholder
    local mcp_config
    mcp_config=$(sed "s|{{INSTALL_DIR}}|$INSTALL_DIR|g" "$mcp_template")

    # Merge teleclaude into mcpServers
    echo "$existing" | jq --argjson mcp "$mcp_config" \
        '.mcpServers.teleclaude = $mcp.mcpServers.teleclaude' > "$claude_config"

    print_success "MCP server added to: $claude_config"
    print_info "Using mcp-wrapper.py at: $INSTALL_DIR/bin/mcp-wrapper.py"
}

# Main installation flow
main() {
    print_header "TeleClaude Installation"

    log "Installation started in $INSTALL_DIR"

    # Pre-flight checks
    detect_os
    check_python
    check_node

    # Install dependencies
    install_system_deps

    # Setup Python environment
    setup_venv

    # Configuration
    setup_config

    # Setup log file
    setup_log_file

    # Install service
    install_service

    # Configure MCP integration
    setup_mcp_config

    # Success message
    print_header "Installation Complete!"

    echo ""
    print_success "TeleClaude has been installed successfully!"
    echo ""
    print_info "Next steps:"
    echo "  1. Go to your Telegram supergroup"
    echo "  2. Send: /new_session"
    echo "  3. Start sending commands!"
    echo ""
    print_info "The daemon is running as a system service and will:"
    echo "  • Start automatically on boot"
    echo "  • Restart automatically if it crashes"
    echo "  • Log to: /var/log/teleclaude.log"
    echo ""
    print_warning "IMPORTANT: Do NOT manually start the daemon!"
    print_warning "The service manages the daemon automatically."
    echo ""

    log "Installation completed successfully"
}

# Run main
main "$@"
