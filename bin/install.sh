#!/usr/bin/env bash
#
# TeleClaude Install Script
# Installs system binaries and Python dependencies.
# Then runs init for first-time setup when safe.
#

set -e

# CRITICAL: Refuse to run from a git worktree
if command -v git &> /dev/null && git rev-parse --git-dir &> /dev/null; then
    GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
    COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)
    if [ "$GIT_DIR" != "$COMMON_DIR" ]; then
        echo "ERROR: Cannot run 'make install' from a git worktree!"
        echo ""
        echo "Running install from a worktree would:"
        echo "  - Repoint the global CLI symlink to the worktree"
        echo "  - Reconfigure the system service to use worktree paths"
        echo "  - Break the main TeleClaude daemon"
        echo ""
        echo "Install must only run from the main repository."
        echo "Worktrees are prepared by install conventions (make install or npm/pnpm install)."
        exit 1
    fi
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="${INSTALL_DIR}/install.log"

PYTHON_MIN_VERSION="3.11"

NON_INTERACTIVE=false
CI_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -y|--yes)
            NON_INTERACTIVE=true
            shift
            ;;
        --ci)
            CI_MODE=true
            NON_INTERACTIVE=true
            shift
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

ensure_teleclaude_yaml() {
    if [ ! -f "$INSTALL_DIR/teleclaude.yml" ]; then
        cat > "$INSTALL_DIR/teleclaude.yml" <<'EOF'
business:
  domains:
    software-development: docs
EOF
        print_success "Created teleclaude.yml"
    else
        print_info "teleclaude.yml already exists"
    fi
}

# Confirm action
confirm() {
    local prompt_text="$1"
    local default="${2:-n}"

    if [ "$NON_INTERACTIVE" = true ]; then
        return 0 # Always assume yes in non-interactive mode
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

    for cmd in python3.14 python3.13 python3.12 python3.11 python3; do
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

    # jq (for JSON manipulation)
    if command -v jq &> /dev/null; then
        print_success "jq already installed"
    else
        print_info "Installing jq..."
        install_package jq
    fi

    if [ "$CI_MODE" = false ]; then
        # ffmpeg (for voice transcription)
        if command -v ffmpeg &> /dev/null; then
            print_success "ffmpeg already installed"
        else
            print_info "Installing ffmpeg..."
            install_package ffmpeg
        fi

        # socat (for MCP socket bridge)
        if command -v socat &> /dev/null; then
            print_success "socat already installed"
        else
            print_info "Installing socat..."
            install_package socat
        fi

        # glow (for pretty markdown rendering in TUI)
        install_glow
    fi

    # Claude Code
    install_claude_code
}

# Install glow (markdown renderer)
install_glow() {
    if command -v glow &> /dev/null; then
        print_success "glow already installed"
        return 0
    fi

    print_info "Installing glow (markdown renderer)..."

    case "$DISTRO" in
        macos)
            if command -v brew &> /dev/null; then
                brew install glow >> "$LOG_FILE" 2>&1
                print_success "glow installed via brew"
            else
                print_warning "Homebrew not found, skipping glow"
            fi
            ;;
        ubuntu|debian)
            # glow is not in default apt repos, use snap if available
            if command -v snap &> /dev/null; then
                sudo snap install glow >> "$LOG_FILE" 2>&1
                print_success "glow installed via snap"
            else
                print_warning "snap not found, skipping glow (install manually: sudo snap install glow)"
            fi
            ;;
        arch|manjaro)
            # Available in community repo
            sudo pacman -S --noconfirm glow >> "$LOG_FILE" 2>&1
            print_success "glow installed via pacman"
            ;;
        *)
            print_warning "Skipping glow on $DISTRO (install manually from https://github.com/charmbracelet/glow)"
            ;;
    esac
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

    has_optional_extra() {
        local extra="$1"
        "$PYTHON_CMD" - "$INSTALL_DIR/pyproject.toml" "$extra" <<'PY'
import sys
import tomllib
from pathlib import Path

pyproject_path = Path(sys.argv[1])
extra = sys.argv[2]
data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
optional = data.get("project", {}).get("optional-dependencies", {})
sys.exit(0 if isinstance(optional, dict) and extra in optional else 1)
PY
    }

    sync_args=()
    for extra in test; do
        if has_optional_extra "$extra"; then
            sync_args+=(--extra "$extra")
        else
            print_warning "Optional dependency extra '$extra' not defined in pyproject.toml; skipping"
        fi
    done

    # On Apple Silicon macOS (non-CI), install local MLX dependencies so
    # Parakeet STT and MLX TTS run in-process (no CLI fallback required).
    if [ "$CI_MODE" = false ] && [ "$OS" = "macos" ] && [ "$(uname -m)" = "arm64" ]; then
        if has_optional_extra "mlx"; then
            sync_args+=(--extra "mlx")
        else
            print_warning "Optional dependency extra 'mlx' not defined in pyproject.toml; skipping"
        fi
    fi

    print_info "Syncing Python environment with uv..."
    if [ "$CI_MODE" = true ] && [ -d "$HOME/Workspace/InstruktAI/TeleClaude/.venv" ]; then
        # CI on self-hosted runner: reuse main checkout's venv to avoid
        # network calls (Little Snitch blocks uv HTTPS on mozmini).
        print_info "Reusing main checkout .venv for CI..."
        MAIN_CHECKOUT="$HOME/Workspace/InstruktAI/TeleClaude"
        cp -a "$MAIN_CHECKOUT/.venv" "$INSTALL_DIR/.venv"
        # Debug: show venv structure so CI logs reveal version mismatches.
        ls -la "$INSTALL_DIR/.venv/bin/python"* || true
        cat "$INSTALL_DIR/.venv/pyvenv.cfg" || true
        ls "$INSTALL_DIR/.venv/lib/" || true
        # Repoint editable install paths to CI checkout directory.
        MAIN_CHECKOUT_ESC=$(printf '%s\n' "$MAIN_CHECKOUT" | sed 's/[&/\]/\\&/g')
        INSTALL_DIR_ESC=$(printf '%s\n' "$INSTALL_DIR" | sed 's/[&/\]/\\&/g')
        find "$INSTALL_DIR/.venv" -path "*/site-packages/__editable__*" \
            \( -name "*.py" -o -name "*.pth" -o -name "direct_url.json" \) \
            -exec sed -i '' "s|$MAIN_CHECKOUT|$INSTALL_DIR|g" {} +
        # Clear cached .pyc so Python picks up the rewritten finder.
        find "$INSTALL_DIR/.venv" -path "*/__pycache__/__editable__*" -name "*.pyc" -delete
        # Verify: can the venv python import a third-party package?
        "$INSTALL_DIR/.venv/bin/python" -c "import sys; print('Python:', sys.version); print('Path:', sys.path)" || true
    elif [ "$CI_MODE" = true ]; then
        # Fallback: try frozen sync (requires uv.lock in checkout).
        (cd "$INSTALL_DIR" && uv sync --frozen "${sync_args[@]}")
    else
        (cd "$INSTALL_DIR" && uv sync "${sync_args[@]}")
    fi

    if [ ! -d "$INSTALL_DIR/.venv" ]; then
        print_error "uv sync did not create .venv"
        exit 1
    fi

    print_success "Python dependencies installed"
}

# Provision log directory
provision_logs() {
    if [ "$CI_MODE" = true ]; then
        return 0
    fi
    print_info "Provisioning log directory..."
    "$INSTALL_DIR/bin/provision-logs.sh" teleclaude
    print_success "Log directory provisioned"
}

# Install global telec CLI symlink
install_global_cli() {
    if [ "$CI_MODE" = true ]; then
        return 0
    fi
    print_header "Installing Global CLI (telec)"

    local target_dir=""
    if [ "$OS" = "macos" ] && [ -d "/opt/homebrew/bin" ]; then
        target_dir="/opt/homebrew/bin"
    elif [ -d "/usr/local/bin" ]; then
        target_dir="/usr/local/bin"
    else
        target_dir="$HOME/.local/bin"
        mkdir -p "$target_dir"
    fi

    local target="$target_dir/telec"
    if [ -w "$target_dir" ]; then
        ln -sf "$INSTALL_DIR/bin/telec" "$target"
    else
        sudo ln -sf "$INSTALL_DIR/bin/telec" "$target"
    fi

    print_success "Installed telec at $target"
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
    install_global_cli
    ensure_teleclaude_yaml

    print_header "Install Complete"
    print_success "Binaries and Python dependencies installed"
    echo ""
    init_args="--yes"
    if [ "$CI_MODE" = true ]; then
        init_args="--ci"
    fi
    "$INSTALL_DIR/bin/init.sh" $init_args

    log "Install completed"
}

main "$@"
