#!/usr/bin/env bash
#
# TeleClaude Install Script
# Installs system binaries and Python dependencies only.
# Run 'make init' after this for first-time setup.
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

PYTHON_MIN_VERSION="3.11"

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

# Check Python version
check_python() {
    print_info "Checking Python version..."

    for cmd in python3.12 python3.11 python3; do
        if command -v "$cmd" &> /dev/null; then
            PYTHON_CMD="$cmd"
            PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')

            if [ "$(printf '%s\n' "$PYTHON_MIN_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" = "$PYTHON_MIN_VERSION" ]; then
                print_success "Found Python $PYTHON_VERSION at $(command -v $cmd)"
                return 0
            fi
        fi
    done

    print_error "Python $PYTHON_MIN_VERSION or higher not found"
    exit 1
}

# Check Node.js
check_node() {
    print_info "Checking Node.js..."

    if ! command -v node &> /dev/null; then
        print_error "Node.js not found (required for Claude Code)"
        print_info "Install: brew install node (macOS) or apt install nodejs npm (Linux)"
        exit 1
    fi

    if ! command -v npm &> /dev/null; then
        print_error "npm not found"
        exit 1
    fi

    NODE_VERSION=$(node --version 2>&1)
    NPM_VERSION=$(npm --version 2>&1)
    print_success "Found Node.js $NODE_VERSION and npm $NPM_VERSION"
}

# Install system dependencies
install_system_deps() {
    print_header "Installing System Dependencies"

    # tmux
    if command -v tmux &> /dev/null; then
        TMUX_VERSION=$(tmux -V | awk '{print $2}')
        print_success "tmux $TMUX_VERSION already installed"
    else
        print_info "Installing tmux..."
        install_package tmux
    fi

    # ffmpeg (for voice transcription)
    if command -v ffmpeg &> /dev/null; then
        print_success "ffmpeg already installed"
    else
        print_info "Installing ffmpeg..."
        install_package ffmpeg
    fi

    # jq (for JSON manipulation)
    if command -v jq &> /dev/null; then
        print_success "jq already installed"
    else
        print_info "Installing jq..."
        install_package jq
    fi

    # socat (for MCP socket bridge)
    if command -v socat &> /dev/null; then
        print_success "socat already installed"
    else
        print_info "Installing socat..."
        install_package socat
    fi

    # Claude Code
    install_claude_code
}

# Install Claude Code
install_claude_code() {
    if command -v claude &> /dev/null; then
        CLAUDE_VERSION=$(claude --version 2>&1 || echo "unknown")
        print_success "Claude Code already installed ($CLAUDE_VERSION)"
        return 0
    fi

    print_info "Installing Claude Code globally via npm..."
    if npm install -g @anthropic-ai/claude-code >> "$LOG_FILE" 2>&1; then
        print_success "Claude Code installed"
    else
        print_warning "Failed to install Claude Code (see $LOG_FILE)"
        print_info "You can install manually: npm install -g @anthropic-ai/claude-code"
    fi
}

# Install uv if needed
install_uv() {
    if command -v uv >/dev/null 2>&1; then
        print_success "uv already installed"
        return 0
    fi

    print_info "Installing uv..."
    case "$OS" in
        macos)
            if ! command -v brew >/dev/null 2>&1; then
                print_error "Homebrew not found. Install from https://brew.sh"
                exit 1
            fi
            brew install uv
            ;;
        linux)
            if command -v apt-get >/dev/null 2>&1; then
                sudo apt-get update -qq && sudo apt-get install -y uv
            else
                print_error "apt-get not found. Install uv manually."
                exit 1
            fi
            ;;
        *)
            print_error "Unsupported OS for uv install"
            exit 1
            ;;
    esac

    if ! command -v uv >/dev/null 2>&1; then
        print_error "uv installation failed"
        exit 1
    fi
    print_success "uv installed"
}

# Install Python dependencies
install_python_deps() {
    print_header "Installing Python Dependencies"

    install_uv

    print_info "Syncing Python environment with uv..."
    uv sync --extra test

    if [ ! -d "$INSTALL_DIR/.venv" ]; then
        print_error "uv sync did not create .venv"
        exit 1
    fi

    print_success "Python dependencies installed"
}

# Provision log directory
provision_logs() {
    print_info "Provisioning log directory..."
    "$INSTALL_DIR/bin/provision-logs.sh" teleclaude
    print_success "Log directory provisioned"
}

# Main
main() {
    print_header "TeleClaude Install"
    log "Install started in $INSTALL_DIR"

    detect_os
    check_python
    check_node

    install_system_deps
    install_python_deps
    provision_logs

    print_header "Install Complete"
    print_success "Binaries and Python dependencies installed"
    echo ""
    print_info "Next step: Run 'make init' for first-time setup"
    echo ""

    log "Install completed"
}

main "$@"
