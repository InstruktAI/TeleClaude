#!/usr/bin/env bash
#
# TeleClaude Install Script
# Installs machine-global binaries, Python dependencies, and agent tooling.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="${INSTALL_DIR}/install.log"

# Runtime config lives under TELECLAUDE_HOME; the repo ships only the blueprint.
TELECLAUDE_HOME="${TELECLAUDE_HOME:-$HOME/.teleclaude}"
TC_CONFIG="${TELECLAUDE_HOME}/config.yml"

PYTHON_MIN_VERSION="3.11"

NON_INTERACTIVE=false
CI_MODE=false

refuse_git_worktree() {
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
}

parse_args() {
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
}

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

ensure_config_yml() {
    if [ ! -f "$TC_CONFIG" ]; then
        mkdir -p "$TELECLAUDE_HOME"
        cp "$INSTALL_DIR/config.sample.yml" "$TC_CONFIG"
        print_success "Created $TC_CONFIG from config.sample.yml"
    else
        print_info "config.yml already exists at $TC_CONFIG"
    fi
}

get_current_agent_enabled() {
    local agent="$1"
    local default_val="$2"
    if [ -f "$TC_CONFIG" ]; then
        "$PYTHON_CMD" -c "
try:
    lines = open('$TC_CONFIG').read().splitlines()
    in_agents = False
    in_agent = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('agents:'):
            in_agents = True
            continue
        if in_agents:
            if line and not line.startswith(' ') and not line.startswith('\t'):
                in_agents = False
                continue
            if stripped.startswith('$agent:'):
                in_agent = True
                continue
            if in_agent:
                if stripped.startswith('enabled:'):
                    print('y' if 'true' in stripped.lower() else 'n')
                    import sys; sys.exit(0)
                elif stripped.endswith(':') and not stripped.startswith('enabled:'):
                    in_agent = False
except Exception:
    pass
print('$default_val')
" 2>/dev/null || echo "$default_val"
    else
        echo "$default_val"
    fi
}

get_current_default_agent() {
    local default_val="$1"
    if [ -f "$TC_CONFIG" ]; then
        "$PYTHON_CMD" -c "
try:
    lines = open('$TC_CONFIG').read().splitlines()
    in_agents = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('agents:'):
            in_agents = True
            continue
        if in_agents:
            if line and not line.startswith(' ') and not line.startswith('\t'):
                in_agents = False
                continue
            if stripped.startswith('default:'):
                print(stripped.split(':', 1)[1].strip())
                import sys; sys.exit(0)
except Exception:
    pass
print('$default_val')
" 2>/dev/null || echo "$default_val"
    else
        echo "$default_val"
    fi
}

setup_agents_interactive() {
    print_header "Interactive Agent Configuration"

    ensure_config_yml

    # Extract current values as defaults
    local default_claude=$(get_current_agent_enabled "claude" "y")
    local default_agy=$(get_current_agent_enabled "gemini" "y")
    local default_codex=$(get_current_agent_enabled "codex" "y")
    local current_default_agent=$(get_current_default_agent "claude")
    if [ "$current_default_agent" = "agy" ]; then
        current_default_agent="gemini"
    fi

    local claude_enabled=false
    local agy_enabled=false
    local codex_enabled=false

    if confirm "Do you want to use Anthropic Claude Code?" "$default_claude"; then
        claude_enabled=true
        install_claude_code
    fi

    if confirm "Do you want to use Google Gemini/Antigravity?" "$default_agy"; then
        agy_enabled=true
        print_info "Installing Google Gemini/Antigravity (agy)..."
        # Download and install agy safely without pipefail issues under set -e
        local install_ok=0
        curl -fsSL https://antigravity.google/install.sh > /tmp/agy_install.sh 2>> "$LOG_FILE" || install_ok=1
        if [ $install_ok -eq 0 ]; then
            bash /tmp/agy_install.sh >> "$LOG_FILE" 2>&1 || install_ok=2
        fi

        if [ $install_ok -eq 0 ]; then
            print_success "Antigravity CLI (agy) installed"
        else
            print_warning "Failed to run agy installation script automatically. Make sure 'agy' is installed and in your PATH."
        fi
    fi

    if confirm "Do you want to use OpenAI Codex?" "$default_codex"; then
        codex_enabled=true
    fi

    # Determine default agent
    local default_agent="claude"
    local enabled_count=0
    local enabled_list=()
    [ "$claude_enabled" = true ] && { enabled_list+=("claude"); ((enabled_count++)); } || true
    [ "$agy_enabled" = true ] && { enabled_list+=("gemini"); ((enabled_count++)); } || true
    [ "$codex_enabled" = true ] && { enabled_list+=("codex"); ((enabled_count++)); } || true

    if [ $enabled_count -eq 0 ]; then
        print_warning "No agents selected. Enabling Claude by default."
        claude_enabled=true
        default_agent="claude"
    elif [ $enabled_count -eq 1 ]; then
        default_agent="${enabled_list[0]}"
    else
        # More than one agent chosen, ask which one to have as default
        # Present current default if it is in the enabled list, otherwise default to first enabled
        local default_selection="$current_default_agent"
        if [[ ! " ${enabled_list[*]} " =~ " ${default_selection} " ]]; then
            default_selection="${enabled_list[0]}"
        fi

        if [ "$NON_INTERACTIVE" = true ]; then
            default_agent="$default_selection"
        else
            while true; do
                read -p "Which agent should be the default? ($(echo "${enabled_list[*]}" | sed 's/ /\//g')) [$default_selection]: " response || true
                response="${response:-$default_selection}"
                response=$(echo "$response" | tr '[:upper:]' '[:lower:]')
                if [[ " ${enabled_list[*]} " =~ " ${response} " ]]; then
                    default_agent="$response"
                    break
                fi
                echo "Invalid selection. Please choose from: ${enabled_list[*]}"
                if [ ! -t 0 ]; then
                    default_agent="$default_selection"
                    break
                fi
            done
        fi
    fi

    print_info "Updating config.yml agents settings..."
    # Python code to update config.yml
    "$PYTHON_CMD" -c "
from pathlib import Path
import sys

def update_agents(path_str, claude_on, agy_on, codex_on, default_name):
    path = Path(path_str)
    if not path.exists():
        return
    content = path.read_text()

    # The config key is 'gemini' (binary resolves to agy); heal any config that
    # a prior installer wrote with the unparseable 'agy:' key.
    content = content.replace('agy:', 'gemini:')

    lines = content.splitlines()
    in_agents = False
    current_agent = None
    default_idx = None
    
    states = {
        'claude': claude_on == 'true',
        'gemini': agy_on == 'true',
        'codex': codex_on == 'true'
    }
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('agents:'):
            in_agents = True
            continue
        if in_agents:
            if line and not line.startswith(' ') and not line.startswith('\t'):
                in_agents = False
                continue
            if stripped.startswith('default:'):
                default_idx = i
                continue
            if stripped.endswith(':') and not stripped.startswith('enabled:'):
                name = stripped[:-1].strip()
                current_agent = name if name in states else None
                continue
            if current_agent and stripped.startswith('enabled:'):
                indent = len(line) - len(stripped)
                val = 'true' if states[current_agent] else 'false'
                lines[i] = ' ' * indent + f'enabled: {val}'
                
    if default_idx is not None:
        indent = len(lines[default_idx]) - len(lines[default_idx].lstrip())
        lines[default_idx] = ' ' * indent + f'default: {default_name}'
        
    path.write_text('\n'.join(lines) + '\n')

update_agents('$TC_CONFIG', '$claude_enabled', '$agy_enabled', '$codex_enabled', '$default_agent')
"
    print_success "config.yml agents updated successfully (default: $default_agent)"
}

# Confirm action
confirm() {
    local prompt_text="$1"
    local default="${2:-n}"

    if [ "$NON_INTERACTIVE" = true ]; then
        return 0 # Always assume yes in non-interactive mode
    fi

    local response
    read -p "$prompt_text (y/n) [$default]: " response || true
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

    # ripgrep (fast file search, used by format.sh for CLAUDE.md cleanup)
    if command -v rg &> /dev/null; then
        print_success "ripgrep already installed"
    else
        print_info "Installing ripgrep..."
        install_package ripgrep
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

        # Redis (conditional native install)
        if confirm "Do you want to install and start a local Redis server?" "y"; then
            if command -v redis-server &> /dev/null; then
                print_success "Redis already installed"
            else
                print_info "Installing Redis..."
                install_package redis
            fi

            print_info "Starting Redis service..."
            if [[ "$OSTYPE" == "darwin"* ]]; then
                brew services start redis >> "$LOG_FILE" 2>&1 || true
            else
                sudo systemctl enable --now redis >> "$LOG_FILE" 2>&1 || true
            fi
            print_success "Redis service management delegated to OS"
        fi
        # glow (for pretty markdown rendering in TUI)
        install_glow
    fi
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

    # All deps use platform markers — plain uv sync installs the right
    # packages for any platform. No extras, no flags, no fragility.
    print_info "Syncing Python environment with uv..."
    if [ "$CI_MODE" = true ]; then
        (cd "$INSTALL_DIR" && uv sync --frozen)
    else
        (cd "$INSTALL_DIR" && uv sync)
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
    "$INSTALL_DIR/bin/provision-logs.sh" teleclaude --non-interactive
    print_success "Log directory provisioned"
}

# Install global telec CLI symlink
install_global_cli() {
    if [ "$CI_MODE" = true ]; then
        return 0
    fi
    print_header "Installing Global CLI (telec)"

    local target_dir=""
    local local_bin="$HOME/.local/bin"
    if [ -d "$local_bin" ] && [[ ":$PATH:" == *":$local_bin:"* ]]; then
        target_dir="$local_bin"
    elif [ "$OS" = "macos" ] && [ -d "/opt/homebrew/bin" ]; then
        target_dir="/opt/homebrew/bin"
    elif [ -d "/usr/local/bin" ]; then
        target_dir="/usr/local/bin"
    elif [ -d "$local_bin" ]; then
        target_dir="$local_bin"
        print_warning "$local_bin exists but is not in PATH; telec may not be globally resolvable"
    else
        target_dir="$local_bin"
        mkdir -p "$target_dir"
        print_warning "Created $local_bin, but it is not in PATH; telec may not be globally resolvable"
    fi

    local target="$target_dir/telec"
    if [ -w "$target_dir" ]; then
        ln -sf "$INSTALL_DIR/bin/telec" "$target"
    else
        sudo ln -sf "$INSTALL_DIR/bin/telec" "$target"
    fi

    print_success "Installed telec at $target"
}

run_macos_setup_action() {
    local action="$1"
    if [ "$OS" != "macos" ]; then
        return 0
    fi

    local cmd=(env "PYTHONPATH=$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" "-m" "teleclaude.entrypoints.macos_setup" "--project-root" "$INSTALL_DIR" "--skip-build")
    cmd+=("$action")

    "${cmd[@]}"
}

install_macos_launchers() {
    if [ "$OS" != "macos" ]; then
        return 0
    fi
    print_header "Deploying macOS Launcher Apps"
    if run_macos_setup_action "install-launchers"; then
        print_success "Launcher apps installed"
    else
        print_error "Failed to install launcher apps"
        exit 1
    fi
}

run_macos_permissions_probe() {
    if [ "$OS" != "macos" ]; then
        return 0
    fi
    run_macos_setup_action "permissions-probe" || true
}

configure_agent_cli() {
    print_header "Configuring Agent CLI"
    print_info "Running bin/init/configure_agent_cli.py..."

    if PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/bin/init/configure_agent_cli.py"; then
        print_success "Agent CLI configured"
    else
        print_error "Failed to configure agent CLI"
    fi
}

setup_git_filters() {
    print_header "Setting up Git Filters"
    print_info "Configuring teleclaude-docs smudge/clean filters..."

    local cmd=(env "PYTHONPATH=$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" "-c" "
from pathlib import Path
from teleclaude.project_setup.git_filters import setup_git_filters
setup_git_filters(Path('$INSTALL_DIR'))
")

    if "${cmd[@]}"; then
        print_success "Git filters configured"
    else
        print_error "Failed to configure Git filters"
        exit 1
    fi
}

# Load modular install steps
source "$INSTALL_DIR/bin/init/setup_mcp_config.sh"
source "$INSTALL_DIR/bin/init/link_shared_scripts.sh"

# Main
main() {
    refuse_git_worktree
    parse_args "$@"

    print_header "TeleClaude Install"
    log "Install started in $INSTALL_DIR"

    detect_os
    check_python
    check_node

    install_system_deps
    install_python_deps
    setup_agents_interactive
    provision_logs
    install_global_cli
    ensure_teleclaude_yaml

    if [ "$CI_MODE" = false ]; then
        install_macos_launchers
    fi

    setup_mcp_config
    configure_agent_cli
    setup_git_filters
    link_shared_scripts

    print_header "Install Complete"
    print_success "Binaries, Python dependencies, and machine-global tooling installed"

    if [ "$CI_MODE" = false ]; then
        run_macos_permissions_probe
    fi

    log "Install completed"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
