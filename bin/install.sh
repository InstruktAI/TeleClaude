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
        cp "$INSTALL_DIR/templates/config.yml" "$TC_CONFIG"
        print_success "Created $TC_CONFIG from the bundled config template"
    else
        print_info "config.yml already exists at $TC_CONFIG"
    fi
}

_yaml_python() {
    if [ -x "$INSTALL_DIR/.venv/bin/python" ]; then
        echo "$INSTALL_DIR/.venv/bin/python"
    else
        echo "$PYTHON_CMD"
    fi
}

get_current_agent_enabled() {
    local agent="$1"
    if [ ! -f "$TC_CONFIG" ]; then
        echo "unset"
        return
    fi
    "$(_yaml_python)" -c "
import sys
try:
    import yaml
except ImportError:
    print('unset'); sys.exit(0)
try:
    with open('$TC_CONFIG') as f:
        data = yaml.safe_load(f) or {}
    agent_cfg = (data.get('agents') or {}).get('$agent')
    if not isinstance(agent_cfg, dict):
        print('unset'); sys.exit(0)
    if 'enabled' not in agent_cfg:
        print('unset'); sys.exit(0)
    val = agent_cfg.get('enabled')
    if isinstance(val, bool):
        print('true' if val else 'false')
    else:
        print('unset')
except Exception:
    print('unset')
" 2>/dev/null || echo "unset"
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

_resolve_agent_enabled() {
    # Resolve agent on/off: honor explicit true/false in config; only prompt when unset.
    # Args: <agent-key> <prompt-text>
    # Echoes "true" or "false" on stdout — status messages go to stderr so callers
    # using $(...) capture only the data value.
    local agent="$1"
    local prompt_text="$2"
    local current
    current=$(get_current_agent_enabled "$agent")
    case "$current" in
        true|false)
            print_info "$agent already configured (enabled=$current); not asking again" >&2
            echo "$current"
            return
            ;;
    esac
    if confirm "$prompt_text" "y" >&2; then
        echo "true"
    else
        echo "false"
    fi
}

setup_agents_interactive() {
    print_header "Interactive Agent Configuration"

    ensure_config_yml

    local current_default_agent=$(get_current_default_agent "claude")
    if [ "$current_default_agent" = "agy" ]; then
        current_default_agent="gemini"
    fi

    local claude_enabled
    local agy_enabled
    local codex_enabled
    claude_enabled=$(_resolve_agent_enabled "claude" "Do you want to use Anthropic Claude Code?")
    agy_enabled=$(_resolve_agent_enabled "gemini" "Do you want to use Google Gemini/Antigravity?")
    codex_enabled=$(_resolve_agent_enabled "codex" "Do you want to use OpenAI Codex?")

    if [ "$claude_enabled" = true ]; then
        install_claude_code
    fi

    if [ "$agy_enabled" = true ]; then
        if command -v agy &> /dev/null; then
            print_info "Antigravity CLI (agy) already installed"
        else
            print_info "Installing Google Gemini/Antigravity (agy)..."
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

        # If the saved default is valid in the current enabled set, keep it — don't re-ask.
        if [[ " ${enabled_list[*]} " =~ " ${current_default_agent} " ]]; then
            default_agent="$current_default_agent"
            print_info "Default agent already configured ($default_agent); not asking again"
        elif [ "$NON_INTERACTIVE" = true ]; then
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
        [[ "$default" =~ ^[Yy]$ ]]
        return
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
        print_info "tmux $TMUX_VERSION already installed"
    else
        print_info "Installing tmux..."
        install_package tmux
    fi

    # jq (for JSON manipulation)
    if command -v jq &> /dev/null; then
        print_info "jq already installed"
    else
        print_info "Installing jq..."
        install_package jq
    fi

    # ripgrep (fast file search, used by format.sh for CLAUDE.md cleanup)
    if command -v rg &> /dev/null; then
        print_info "ripgrep already installed"
    else
        print_info "Installing ripgrep..."
        install_package ripgrep
    fi

    if [ "$CI_MODE" = false ]; then
        # ffmpeg (for voice transcription)
        if command -v ffmpeg &> /dev/null; then
            print_info "ffmpeg already installed"
        else
            print_info "Installing ffmpeg..."
            install_package ffmpeg
        fi

        # socat (for MCP socket bridge)
        if command -v socat &> /dev/null; then
            print_info "socat already installed"
        else
            print_info "Installing socat..."
            install_package socat
        fi

        # Redis (conditional native install) — skip when a remote Redis is already
        # configured in .env. A local server is only needed when no REDIS_URL is set
        # or its host is loopback; a configured remote endpoint needs nothing here.
        # Classification (loopback vs remote) lives in bin/init/redis_locality.sh.
        local redis_url_value=""
        [ -f "$INSTALL_DIR/.env" ] && redis_url_value="$(grep -E '^REDIS_URL=.+' "$INSTALL_DIR/.env" | head -1)"
        redis_url_value="${redis_url_value#REDIS_URL=}"
        if redis_url_skips_local_install "$redis_url_value"; then
            print_info "Remote Redis already configured (REDIS_URL host=$(redis_url_host "$redis_url_value")) — skipping local Redis install"
        elif confirm "Do you want to install and start a local Redis server?" "y"; then
            if command -v redis-server &> /dev/null; then
                print_info "Redis already installed"
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

        # macOS-only optional GUI casks (LM Studio: local summarizer; Handy: STT)
        install_macos_casks
    fi
}

# Install optional macOS GUI apps via brew cask. Skips silently if not on macOS,
# if Homebrew is missing, or if the cask is already installed.
install_macos_casks() {
    if [ "$OS" != "macos" ]; then
        return 0
    fi
    if ! command -v brew &> /dev/null; then
        print_warning "Homebrew not found; skipping macOS cask prompts"
        return 0
    fi

    _maybe_install_cask "lm-studio" "Install LM Studio (local LLM server for summarizer)?"
    _maybe_install_cask "handy" "Install Handy (macOS speech-to-text app)?"
}

_maybe_install_cask() {
    local cask="$1"
    local prompt_text="$2"
    if brew list --cask "$cask" &> /dev/null; then
        print_info "$cask cask already installed"
        return 0
    fi
    if confirm "$prompt_text" "y"; then
        print_info "Installing $cask via brew cask..."
        if brew install --cask "$cask" >> "$LOG_FILE" 2>&1; then
            print_success "$cask installed"
        else
            print_warning "Failed to install $cask cask (see $LOG_FILE)"
        fi
    fi
}

# Install Claude Code
install_claude_code() {
    if command -v claude &> /dev/null; then
        CLAUDE_VERSION=$(claude --version 2>&1 || echo "unknown")
        print_info "Claude Code already installed ($CLAUDE_VERSION)"
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
        print_info "uv already installed"
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

validate_config() {
    print_header "Validating config.yml"
    if "$INSTALL_DIR/bin/telec" config validate; then
        print_success "config.yml is valid"
    else
        print_error "config.yml validation failed — fix the errors above and re-run install"
        exit 1
    fi
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
source "$INSTALL_DIR/bin/init/redis_locality.sh"
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
    validate_config
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
