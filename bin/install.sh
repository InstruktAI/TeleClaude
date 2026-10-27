#!/usr/bin/env bash
#
# TeleClaude Install Script
# Installs machine-global binaries, Python dependencies, and agent tooling.
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="${INSTALL_DIR}/install.log"
readonly INSTALL_LOG_LEVEL="${TELECLAUDE_LOG_LEVEL:-INFO}"

# Runtime config lives under TELECLAUDE_HOME; the repo ships only the blueprint.
TELECLAUDE_HOME="${TELECLAUDE_HOME:-$HOME/.teleclaude}"
TC_CONFIG="${TELECLAUDE_HOME}/config.yml"

PYTHON_MIN_VERSION="3.12"
# Oldest corepack that can launch pnpm 11+.
COREPACK_MIN_VERSION="0.34.5"
# Corepack installed when the one on PATH is too old: the newest release that
# launches pnpm 11+ while its declared Node engine range still includes the
# Node 22/24 patch releases that later corepack majors drop.
COREPACK_INSTALL_VERSION="0.34.7"
source "$INSTALL_DIR/bin/init/tool_versions.sh"
# shellcheck source=/dev/null
source "$INSTALL_DIR/bin/init/live_root.sh"
# The path live surfaces (the published telec, links, service definitions) name for this checkout.
LIVE_ROOT="$(live_root_of "$INSTALL_DIR")"

# Installer output goes to the log file, so a corepack download confirmation
# would block on input nobody can see.
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

NON_INTERACTIVE=false
CI_MODE=false
DEPS_ONLY_MODE=false

# Whether this checkout is a release of the installation (a folder of its releases): a release is a
# full build, never a development checkout.
is_installation_release() {
    is_installation_release_dir "$INSTALL_DIR"
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
            --deps-only)
                DEPS_ONLY_MODE=true
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

select_install_mode() {
    if [ "$CI_MODE" = false ] && [ "$DEPS_ONLY_MODE" = false ]; then
        # A checkout that is not a release of the installation prepares only its own development
        # environment: it deploys no service, publishes no telec, and writes no agent hook or home link.
        if ! is_installation_release; then
            DEPS_ONLY_MODE=true
            NON_INTERACTIVE=true
        elif [ -n "${CI:-}" ]; then
            CI_MODE=true
            NON_INTERACTIVE=true
        elif [ ! -t 0 ]; then
            NON_INTERACTIVE=true
        fi
    fi
}

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

# Run in the caller's shell so exported bootstrap paths remain available.
# Keep the command outside a conditional: testing its status would disable
# errexit inside the function. Failed stages keep their original error handling.
run_install_stage() {
    local stage="$1"
    shift
    local started=$SECONDS
    "$@"
    log_install_stage "$stage" "$((SECONDS - started))"
}

# Shell-native structured formatting avoids starting Python for each stage.
log_install_stage() {
    case "$INSTALL_LOG_LEVEL" in
        DEBUG|TRACE|debug|trace)
            printf 'time=%s level=DEBUG event=install_stage_completed stage=%s duration_s=%s\n' \
                "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" "$2" >> "$LOG_FILE"
            ;;
    esac
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

_run_sudo() {
    local step="$1"
    shift
    if [ "$NON_INTERACTIVE" = true ]; then
        if sudo -n "$@"; then
            return 0
        fi
        print_error "$step needs sudo access that works without a prompt; run install from an authorized terminal or provide non-interactive sudo access"
        return 1
    fi
    if sudo "$@"; then
        return 0
    fi
    print_error "$step failed"
    return 1
}

_run_agent_cli_installer() {
    if [ "$NON_INTERACTIVE" = true ] || [ ! -t 0 ]; then
        "$@" </dev/null
    else
        "$@"
    fi
}

ensure_teleclaude_yaml() {
    if [ ! -f "$INSTALL_DIR/teleclaude.yml" ]; then
        cat > "$INSTALL_DIR/teleclaude.yml" <<'EOF'
# yaml-language-server: $schema=schemas/teleclaude-global.schema.json
kind: global
EOF
        print_success "Created teleclaude.yml"
    else
        print_info "teleclaude.yml already exists"
    fi
}

ensure_config_yml() {
    "$(_yaml_python)" "$INSTALL_DIR/bin/init/ensure_machine_config.py"
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
    PYTHONPATH="$INSTALL_DIR" "$(_yaml_python)" "$INSTALL_DIR/bin/init/configure_machine_agents.py" --inspect 2>/dev/null \
        | awk -F= -v key="$agent" '$1 == key {print $2; found=1} END {if (!found) print "unset"}'
}

get_current_default_agent() {
    local default_val="$1"
    local configured
    configured=$(PYTHONPATH="$INSTALL_DIR" "$(_yaml_python)" "$INSTALL_DIR/bin/init/configure_machine_agents.py" --inspect 2>/dev/null \
        | awk -F= '$1 == "default" {print $2; found=1} END {if (!found) print ""}')
    echo "${configured:-$default_val}"
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

list_contains() {
    local needle="$1"
    shift
    local item
    for item in "$@"; do
        if [ "$item" = "$needle" ]; then
            return 0
        fi
    done
    return 1
}

update_agent_cli() {
    local display_name="$1"
    shift

    print_info "Checking for $display_name updates..."
    if "$@" </dev/null >> "$LOG_FILE" 2>&1; then
        print_success "$display_name is up to date"
    else
        print_warning "Failed to update $display_name (see $LOG_FILE); continuing with the installed version"
    fi
}

# This script's install/enable handling below knows exactly these agents.
# Adding a canonical agent to teleclaude/agent_registry.py without adding its
# install/enable branch here is a packaging omission — fail loudly instead of
# silently offering an incomplete agent list.
_KNOWN_INSTALL_AGENTS="claude codex gemini deepseek"

assert_agent_install_coverage() {
    local canonical
    canonical=$(PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" -m teleclaude.codegen.agent_registry --list)
    local agent
    for agent in $canonical; do
        case " $_KNOWN_INSTALL_AGENTS " in
            *" $agent "*) ;;
            *)
                print_error "bin/install.sh has no install/enable handling for canonical agent '$agent'"
                print_error "Add its branch to setup_agents_interactive() before re-running install."
                exit 1
                ;;
        esac
    done
}

setup_agents_interactive() {
    print_header "Interactive Agent Configuration"

    assert_agent_install_coverage
    local current_default_agent
    current_default_agent=$(get_current_default_agent "claude")
    if [ "$current_default_agent" = "agy" ]; then
        current_default_agent="gemini"
    fi

    local claude_enabled
    local agy_enabled
    local codex_enabled
    local deepseek_enabled
    claude_enabled=$(_resolve_agent_enabled "claude" "Do you want to use Anthropic Claude Code?")
    agy_enabled=$(_resolve_agent_enabled "gemini" "Do you want to use Google Gemini/Antigravity?")
    codex_enabled=$(_resolve_agent_enabled "codex" "Do you want to use OpenAI Codex?")
    deepseek_enabled=$(_resolve_agent_enabled "deepseek" "Do you want to use DeepSeek Harness (dsh)?")

    if [ "$claude_enabled" = true ]; then
        install_claude_code
    fi

    if [ "$agy_enabled" = true ]; then
        if command -v agy &> /dev/null; then
            update_agent_cli "Antigravity CLI (agy)" agy update
        else
            print_info "Installing Google Gemini/Antigravity (agy)..."
            local install_ok=0
            curl -fsSL https://antigravity.google/cli/install.sh > /tmp/agy_install.sh 2>> "$LOG_FILE" || install_ok=1
            if [ $install_ok -eq 0 ]; then
                _run_agent_cli_installer bash /tmp/agy_install.sh >> "$LOG_FILE" 2>&1 || install_ok=2
            fi
            if [ $install_ok -eq 0 ]; then
                print_success "Antigravity CLI (agy) installed"
            else
                print_warning "Failed to run agy installation script automatically. Make sure 'agy' is installed and in your PATH."
            fi
        fi
    fi

    if [ "$codex_enabled" = true ]; then
        if command -v codex &> /dev/null; then
            update_agent_cli "OpenAI Codex CLI" codex update
        else
            print_info "Installing OpenAI Codex CLI..."
            local install_ok=0
            curl -fsSL https://chatgpt.com/codex/install.sh > /tmp/codex_install.sh 2>> "$LOG_FILE" || install_ok=1
            if [ $install_ok -eq 0 ]; then
                CODEX_NON_INTERACTIVE=1 _run_agent_cli_installer sh /tmp/codex_install.sh >> "$LOG_FILE" 2>&1 || install_ok=2
            fi
            if [ $install_ok -eq 0 ]; then
                print_success "OpenAI Codex CLI installed"
            else
                print_warning "Failed to run codex installation script automatically. Make sure 'codex' is installed and in your PATH."
            fi
        fi
    fi

    if [ "$deepseek_enabled" = true ]; then
        # Remove the legacy global TUI package before repairing the CLI installation.
        if npm list -g --depth=0 @deepseek-harness-tui/dsh-tui >/dev/null 2>&1; then
            print_info "Removing legacy global DeepSeek TUI package..."
            if npm uninstall -g @deepseek-harness-tui/dsh-tui >> "$LOG_FILE" 2>&1; then
                print_success "Legacy global DeepSeek TUI package removed"
            else
                print_warning "Failed to remove the legacy global DeepSeek TUI package (see $LOG_FILE)"
            fi
        fi

        setup_dsh_integration
    fi

    # Determine default agent
    local default_agent="claude"
    local enabled_count=0
    local enabled_list=()
    [ "$claude_enabled" = true ] && { enabled_list+=("claude"); ((enabled_count++)); } || true
    [ "$agy_enabled" = true ] && { enabled_list+=("gemini"); ((enabled_count++)); } || true
    [ "$codex_enabled" = true ] && { enabled_list+=("codex"); ((enabled_count++)); } || true
    [ "$deepseek_enabled" = true ] && { enabled_list+=("deepseek"); ((enabled_count++)); } || true

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
        if ! list_contains "$default_selection" "${enabled_list[@]}"; then
            default_selection="${enabled_list[0]}"
        fi

        # If the saved default is valid in the current enabled set, keep it — don't re-ask.
        if list_contains "$current_default_agent" "${enabled_list[@]}"; then
            default_agent="$current_default_agent"
            print_info "Default agent already configured ($default_agent); not asking again"
        elif [ "$NON_INTERACTIVE" = true ]; then
            default_agent="$default_selection"
        else
            while true; do
                read -r -p "Which agent should be the default? ($(echo "${enabled_list[*]}" | sed 's/ /\//g')) [$default_selection]: " response || true
                response="${response:-$default_selection}"
                response=$(echo "$response" | tr '[:upper:]' '[:lower:]')
                if list_contains "$response" "${enabled_list[@]}"; then
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
    PYTHONPATH="$INSTALL_DIR" "$(_yaml_python)" "$INSTALL_DIR/bin/init/configure_machine_agents.py" --apply \
        --claude "$claude_enabled" --gemini "$agy_enabled" --codex "$codex_enabled" \
        --deepseek "$deepseek_enabled" --default "$default_agent"
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
    read -r -p "$prompt_text (y/n) [$default]: " response || true
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
                # shellcheck source=/dev/null
                . /etc/os-release
                DISTRO="${ID:-unknown}"
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
            _run_sudo "refresh apt package lists before installing $package" apt-get update -qq
            _run_sudo "install $package with apt-get" apt-get install -y "$package"
            ;;
        fedora|rhel|centos)
            _run_sudo "install $package with dnf" dnf install -y "$package"
            ;;
        arch|manjaro)
            _run_sudo "install $package with pacman" pacman -S --noconfirm "$package"
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

# Distribution package that provides the libarchive shared library
libarchive_package() {
    case "$DISTRO" in
        ubuntu|debian)
            # Stable name across the libarchive13 / libarchive13t64 rename; depends on the library package
            echo "libarchive-tools"
            ;;
        *)
            echo "libarchive"
            ;;
    esac
}

# Check Python version
check_python() {
    print_info "Checking Python version..."

    for cmd in python3.14 python3.13 python3.12 python3; do
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
        print_error "Node.js not found (required for TeleClaude tooling)"
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

corepack_version() {
    if command -v corepack &> /dev/null; then
        corepack --version 2>/dev/null || true
    fi
}

corepack_meets_minimum() {
    local version="$1"
    [ -n "$version" ] && [ "$(printf '%s\n' "$COREPACK_MIN_VERSION" "$version" | sort -V | head -n1)" = "$COREPACK_MIN_VERSION" ]
}

# Ensure a new-enough corepack is present and attempt to enable its package-manager shims.
# Corepack ships bundled-but-disabled with most Node builds, is being unbundled
# in newer Node, and is split out by some distros — and a bundled copy can be
# too old — so we install it from npm rather than assume a usable one exists.
setup_corepack() {
    print_info "Ensuring corepack..."
    local version
    version=$(corepack_version)
    if ! corepack_meets_minimum "$version"; then
        print_info "corepack ${version:-not found} is older than $COREPACK_MIN_VERSION — installing corepack@$COREPACK_INSTALL_VERSION via npm"
        if ! npm install -g "corepack@$COREPACK_INSTALL_VERSION" >> "$LOG_FILE" 2>&1; then
            print_error "Failed to install corepack"
            exit 1
        fi
        hash -r
        version=$(corepack_version)
        if ! corepack_meets_minimum "$version"; then
            print_error "corepack on PATH is ${version:-missing} after install; need $COREPACK_MIN_VERSION or newer"
            exit 1
        fi
        # Cached package managers carry the launch entry the previous corepack
        # recorded, which is wrong for pnpm 11+; clearing forces a fresh fetch.
        if ! corepack cache clean >> "$LOG_FILE" 2>&1; then
            print_error "Failed to clear the corepack cache; stale pnpm entries would still be launched"
            exit 1
        fi
    fi
    if corepack enable >> "$LOG_FILE" 2>&1; then
        print_success "corepack ready"
    else
        print_warning "Corepack could not install package-manager shims in its default location; see $LOG_FILE for the error"
    fi
}

# Install the pinned Prettier the quality runner's root formatting legs call.
setup_prettier() {
    print_info "Ensuring prettier@$PRETTIER_INSTALL_VERSION..."
    local installed_version=""
    if command -v prettier >/dev/null 2>&1 && installed_version=$(prettier --version 2>/dev/null); then
        if [ "$installed_version" = "$PRETTIER_INSTALL_VERSION" ]; then
            print_success "prettier already at the required version"
            return 0
        fi
    fi
    if ! npm install -g "prettier@$PRETTIER_INSTALL_VERSION" >> "$LOG_FILE" 2>&1; then
        print_error "Failed to install prettier"
        exit 1
    fi
    hash -r
    print_success "prettier ready"
}

# Pinned together from gogcli's release checksums.txt.
GOG_VERSION="0.38.1"
GOG_LINUX_AMD64_SHA256="6576828ed6852949ba424b967c3ff4268b3d9c90e201f90fe3d539fe3a151ebb"
GOG_LINUX_ARM64_SHA256="462342542472dcf361744cfe5e15a3540364b4c5120577e4519fffbd1afc6596"

# The tool reports SQLite's canonical source ID through --version.
SQLITE3_RSYNC_VERSION="3.53.4"
SQLITE3_RSYNC_RELEASE="3530400"
SQLITE3_RSYNC_YEAR="2026"
SQLITE3_RSYNC_SOURCE_ID="2026-07-24 19:02:57 bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc"
SQLITE3_RSYNC_OSX_ARM64_SHA3="58d53e0eb69c17cabebed2754bf399e4d44939be42dcf194769c00078bfd776d"
SQLITE3_RSYNC_OSX_ARM64_SHA256="e56768d61017ab3dbd9ff5690b5551846d9945830fdc0b8a9610df722f05e33b"
SQLITE3_RSYNC_OSX_X64_SHA3="3353bb4e5ac54f85c5b82012d30476d20539a9495abdd11a1707df578cff2d7e"
SQLITE3_RSYNC_OSX_X64_SHA256="76c187f19990c4a6fe9a4f8d01de038a63fc339aaf9d491202c9c56d058cb110"
SQLITE3_RSYNC_LINUX_X64_SHA3="6eeb57e8f2aef7687f9f016a980992cf2799c8c07a87c5e21495530f91915047"
SQLITE3_RSYNC_LINUX_X64_SHA256="7a6f4d1720e4bc13faa3d934bfce37b816a496c0a2480deacd64cfd8be6cf224"
SQLITE3_RSYNC_SOURCE_SHA3="b834d474b9b393d85a9e3ee4cc11f1329e007e9376a424ee740796f5c4bda3a8"
SQLITE3_RSYNC_SOURCE_SHA256="d18fa15aec74d8c17e1463f861095adc01b5ad190256acb4f91d22f0368d232b"

install_sqlite3_rsync() {
    local installed_tool="$TELEC_BIN_DIR/sqlite3_rsync"
    local installed_source_id=""
    if [ -x "$installed_tool" ] && installed_source_id=$("$installed_tool" --version 2>&1); then
        if [ "$installed_source_id" = "$SQLITE3_RSYNC_SOURCE_ID" ]; then
            print_info "sqlite3_rsync $SQLITE3_RSYNC_VERSION already installed"
            _ensure_local_bin_on_path
            return 0
        fi
    fi

    local artifact_name expected_sha archive_path temp_dir source_dir build_dir actual_sha
    case "$OS:$(uname -m)" in
        macos:arm64|macos:aarch64)
            artifact_name="sqlite-tools-osx-arm64-$SQLITE3_RSYNC_RELEASE.zip"
            expected_sha="$SQLITE3_RSYNC_OSX_ARM64_SHA256"
            ;;
        macos:x86_64|macos:amd64)
            artifact_name="sqlite-tools-osx-x64-$SQLITE3_RSYNC_RELEASE.zip"
            expected_sha="$SQLITE3_RSYNC_OSX_X64_SHA256"
            ;;
        linux:x86_64|linux:amd64)
            artifact_name="sqlite-tools-linux-x64-$SQLITE3_RSYNC_RELEASE.zip"
            expected_sha="$SQLITE3_RSYNC_LINUX_X64_SHA256"
            ;;
        linux:aarch64|linux:arm64)
            artifact_name="sqlite-src-$SQLITE3_RSYNC_RELEASE.zip"
            expected_sha="$SQLITE3_RSYNC_SOURCE_SHA256"
            ;;
        *)
            print_error "sqlite3_rsync provisioning is unsupported on $OS/$(uname -m). See $LOG_FILE"
            exit 1
            ;;
    esac

    local artifact_url="https://www.sqlite.org/$SQLITE3_RSYNC_YEAR/$artifact_name"
    if ! temp_dir=$(mktemp -d); then
        print_error "Failed to create a temporary directory for sqlite3_rsync provisioning. See $LOG_FILE"
        exit 1
    fi
    trap 'rm -rf "$temp_dir"' EXIT

    archive_path="$temp_dir/$artifact_name"
    if ! curl -fsSL "$artifact_url" -o "$archive_path" >> "$LOG_FILE" 2>&1; then
        print_error "Failed to download sqlite3_rsync release $artifact_url. See $LOG_FILE"
        exit 1
    fi

    if command -v sha256sum &> /dev/null; then
        if ! actual_sha=$(sha256sum "$archive_path" | awk '{print $1}'); then
            print_error "Failed to calculate sqlite3_rsync release SHA-256. See $LOG_FILE"
            exit 1
        fi
    elif command -v shasum &> /dev/null; then
        if ! actual_sha=$(shasum -a 256 "$archive_path" | awk '{print $1}'); then
            print_error "Failed to calculate sqlite3_rsync release SHA-256. See $LOG_FILE"
            exit 1
        fi
    else
        print_error "Cannot verify sqlite3_rsync integrity: sha256sum or shasum is required. See $LOG_FILE"
        exit 1
    fi
    if [ "$actual_sha" != "$expected_sha" ]; then
        print_error "sqlite3_rsync release verification failed: expected $expected_sha, got $actual_sha. See $LOG_FILE"
        exit 1
    fi

    local staged_tool="$temp_dir/sqlite3_rsync"
    if [ "$OS" = "linux" ] && { [ "$(uname -m)" = "aarch64" ] || [ "$(uname -m)" = "arm64" ]; }; then
        source_dir="$temp_dir/sqlite-src-$SQLITE3_RSYNC_RELEASE"
        build_dir="$temp_dir/build"
        if ! python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$archive_path" "$temp_dir" >> "$LOG_FILE" 2>&1; then
            print_error "Failed to extract verified SQLite source archive. See $LOG_FILE"
            exit 1
        fi
        if [ ! -f "$source_dir/configure" ] || [ ! -d "$source_dir/autosetup" ]; then
            print_error "Verified SQLite source archive is missing its configure build files. See $LOG_FILE"
            exit 1
        fi
        if ! chmod +x "$source_dir/configure" "$source_dir"/autosetup/autosetup-*; then
            print_error "Failed to prepare SQLite source build scripts. See $LOG_FILE"
            exit 1
        fi
        if ! command -v gcc &> /dev/null; then
            print_error "Cannot build sqlite3_rsync on Linux aarch64: gcc is required. See $LOG_FILE"
            exit 1
        fi
        if ! command -v make &> /dev/null; then
            print_error "Cannot build sqlite3_rsync on Linux aarch64: make is required. See $LOG_FILE"
            exit 1
        fi
        if ! mkdir -p "$build_dir"; then
            print_error "Failed to create the temporary SQLite build directory. See $LOG_FILE"
            exit 1
        fi
        if ! (cd "$build_dir" && "$source_dir/configure" && make sqlite3_rsync) >> "$LOG_FILE" 2>&1; then
            print_error "Failed to build sqlite3_rsync from the verified source archive. See $LOG_FILE"
            exit 1
        fi
        if [ ! -f "$build_dir/sqlite3_rsync" ] || ! cp "$build_dir/sqlite3_rsync" "$staged_tool"; then
            print_error "SQLite source build did not produce sqlite3_rsync. See $LOG_FILE"
            exit 1
        fi
    else
        if ! python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extract("sqlite3_rsync", sys.argv[2])' "$archive_path" "$temp_dir" >> "$LOG_FILE" 2>&1; then
            print_error "Failed to extract sqlite3_rsync from the verified tools archive. See $LOG_FILE"
            exit 1
        fi
    fi

    if [ ! -f "$staged_tool" ] || ! chmod +x "$staged_tool"; then
        print_error "Verified SQLite artifact did not produce an executable sqlite3_rsync. See $LOG_FILE"
        exit 1
    fi
    local staged_source_id=""
    if ! staged_source_id=$("$staged_tool" --version 2>&1); then
        print_error "New sqlite3_rsync could not report its SQLite source ID. See $LOG_FILE"
        exit 1
    fi
    if [ "$staged_source_id" != "$SQLITE3_RSYNC_SOURCE_ID" ]; then
        print_error "New sqlite3_rsync source ID mismatch: expected $SQLITE3_RSYNC_SOURCE_ID, got $staged_source_id. See $LOG_FILE"
        exit 1
    fi

    if ! mkdir -p "$TELEC_BIN_DIR"; then
        print_error "Failed to create $TELEC_BIN_DIR for sqlite3_rsync. See $LOG_FILE"
        exit 1
    fi
    if ! mv "$staged_tool" "$installed_tool"; then
        print_error "Failed to place sqlite3_rsync in $TELEC_BIN_DIR. See $LOG_FILE"
        exit 1
    fi
    if ! chmod +x "$installed_tool"; then
        print_error "Failed to make sqlite3_rsync executable in $TELEC_BIN_DIR. See $LOG_FILE"
        exit 1
    fi
    _ensure_local_bin_on_path
    print_success "Installed sqlite3_rsync $SQLITE3_RSYNC_VERSION"

    if ! rm -rf "$temp_dir"; then
        print_error "Failed to clean up sqlite3_rsync provisioning files. See $LOG_FILE"
        exit 1
    fi
    trap - EXIT
}

install_gog() {
    local installed_version
    if command -v gog &> /dev/null; then
        if ! installed_version=$(gog --version 2>&1); then
            print_error "gog is present but its version could not be read"
            exit 1
        fi
        print_info "gog already installed: $installed_version"
        return 0
    fi

    if [ "$OS" = "macos" ] || command -v brew &> /dev/null; then
        if ! command -v brew &> /dev/null; then
            print_error "Homebrew not found. Please install from https://brew.sh"
            exit 1
        fi
        if ! brew install openclaw/tap/gogcli >> "$LOG_FILE" 2>&1; then
            print_error "Failed to install gog with openclaw/tap/gogcli. See $LOG_FILE"
            exit 1
        fi
        if ! installed_version=$(gog --version 2>&1); then
            print_error "gog was installed but its version could not be read"
            exit 1
        fi
        print_success "Installed gog: $installed_version"
        return 0
    fi

    if [ "$OS" != "linux" ]; then
        print_error "gog provisioning is unsupported on $OS"
        exit 1
    fi

    # Linux hosts without Homebrew use the pinned release artifact directly.
    local gog_arch expected_sha archive_name archive_url temp_dir archive_path actual_sha
    case "$(uname -m)" in
        x86_64|amd64)
            gog_arch="amd64"
            expected_sha="$GOG_LINUX_AMD64_SHA256"
            ;;
        aarch64|arm64)
            gog_arch="arm64"
            expected_sha="$GOG_LINUX_ARM64_SHA256"
            ;;
        *)
            print_error "Unsupported Linux architecture for gog: $(uname -m)"
            exit 1
            ;;
    esac

    archive_name="gogcli_${GOG_VERSION}_linux_${gog_arch}.tar.gz"
    archive_url="https://github.com/openclaw/gogcli/releases/download/v${GOG_VERSION}/${archive_name}"
    if ! temp_dir=$(mktemp -d); then
        print_error "Failed to create a temporary directory for gog provisioning"
        exit 1
    fi
    trap 'rm -rf "$temp_dir"' EXIT

    archive_path="$temp_dir/$archive_name"
    if ! curl -fsSL "$archive_url" -o "$archive_path" >> "$LOG_FILE" 2>&1; then
        print_error "Failed to download gog release $archive_url. See $LOG_FILE"
        exit 1
    fi

    if command -v sha256sum &> /dev/null; then
        if ! actual_sha=$(sha256sum "$archive_path" | awk '{print $1}'); then
            print_error "Failed to calculate the gog release SHA-256"
            exit 1
        fi
    elif command -v shasum &> /dev/null; then
        if ! actual_sha=$(shasum -a 256 "$archive_path" | awk '{print $1}'); then
            print_error "Failed to calculate the gog release SHA-256"
            exit 1
        fi
    else
        print_error "Cannot verify gog release integrity: sha256sum or shasum is required"
        exit 1
    fi
    if [ "$actual_sha" != "$expected_sha" ]; then
        print_error "gog release verification failed: expected $expected_sha, got $actual_sha"
        exit 1
    fi

    if ! tar -xzf "$archive_path" -C "$temp_dir" >> "$LOG_FILE" 2>&1; then
        print_error "Failed to extract verified gog release. See $LOG_FILE"
        exit 1
    fi
    if [ ! -f "$temp_dir/gog" ]; then
        print_error "Verified gog release did not contain the gog binary"
        exit 1
    fi
    if ! mkdir -p "$TELEC_BIN_DIR"; then
        print_error "Failed to create $TELEC_BIN_DIR for gog"
        exit 1
    fi
    if ! mv "$temp_dir/gog" "$TELEC_BIN_DIR/gog"; then
        print_error "Failed to place gog in $TELEC_BIN_DIR"
        exit 1
    fi
    if ! chmod +x "$TELEC_BIN_DIR/gog"; then
        print_error "Failed to make gog executable in $TELEC_BIN_DIR"
        exit 1
    fi
    _ensure_local_bin_on_path
    if ! installed_version=$("$TELEC_BIN_DIR/gog" --version 2>&1); then
        print_error "gog was placed but its version could not be read"
        exit 1
    fi
    print_success "Installed gog $installed_version from pinned release $GOG_VERSION"

    if ! rm -rf "$temp_dir"; then
        print_error "Failed to clean up gog provisioning files"
        exit 1
    fi
    trap - EXIT
}

# Install system dependencies
# Brings a local Redis up without assuming it is down. Probing first keeps a
# repeat install quiet instead of re-announcing a service that never stopped.
ensure_local_redis_running() {
    if redis-cli ping 2>/dev/null | grep -q PONG; then
        print_info "Redis already running"
        return 0
    fi

    print_info "Starting Redis service..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew services start redis >> "$LOG_FILE" 2>&1 || true
    else
        if ! _run_sudo "enable and start the Redis service" systemctl enable --now redis 2>&1 | tee -a "$LOG_FILE" > /dev/null; then
            print_error "Could not enable and start Redis; ensure the unattended installer can use sudo and re-run make install"
            exit 1
        fi
    fi
    print_success "Redis service management delegated to OS"
}

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

    # ripgrep (fast file search used by TeleClaude tooling)
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

        # libarchive shared library (for chiptunes HVSC corpus extraction via the libarchive-c binding)
        if python3 -c 'import ctypes.util, sys; sys.exit(0 if ctypes.util.find_library("archive") else 1)' &> /dev/null; then
            print_info "libarchive already installed"
        else
            print_info "Installing libarchive..."
            install_package "$(libarchive_package)"
        fi

        install_gog
        install_sqlite3_rsync

        # Redis: every computer runs one. Where the cluster Redis is remote it is this computer's local Redis,
        # configured by the setup_local_redis stage; where the cluster Redis URL is loopback or unset it is the
        # cluster Redis itself. Classification (loopback vs remote) lives in bin/init/redis_locality.sh.
        local redis_url_value
        redis_url_value="$(machine_cluster_redis_url "${TELECLAUDE_HOME:-$HOME/.teleclaude}/.env")"
        if command -v redis-server &> /dev/null; then
            print_info "Redis already installed"
        else
            print_info "Installing Redis..."
            install_package redis
        fi
        if ! redis_url_skips_local_install "$redis_url_value"; then
            ensure_local_redis_running
        fi

        # macOS-only optional GUI casks (LM Studio: local summarizer; Handy: STT)
        install_macos_casks
    fi
}

# Install optional macOS GUI apps via brew cask. Skips silently if not on macOS,
# if Homebrew is missing, or if the app is already installed (registered as a
# brew cask, or found as an app bundle in /Applications).
install_macos_casks() {
    if [ "$OS" != "macos" ]; then
        return 0
    fi
    if ! command -v brew &> /dev/null; then
        print_warning "Homebrew not found; skipping macOS cask prompts"
        return 0
    fi

    local lm_studio_chosen=false
    if _maybe_install_cask "lm-studio" "Install LM Studio (local LLM server for summarizer)?" "LM Studio"; then
        lm_studio_chosen=true
    fi
    if [ "$lm_studio_chosen" = true ]; then
        _ensure_llmster_installed
    elif [ "$NON_INTERACTIVE" = false ] && [ -t 0 ] && { brew list --cask lm-studio &> /dev/null || [ -d "/Applications/LM Studio.app" ]; } && ! _resolve_lms_binary >/dev/null; then
        if confirm "Install the llmster background service for existing LM Studio?" "n"; then
            _ensure_llmster_installed
        fi
    fi
    # A skipped optional cask is a normal outcome, not a failure of this step.
    _maybe_install_cask "handy" "Install Handy (macOS speech-to-text app)?" "Handy" || true
}

# Resolves lms the way its own installer does: PATH, then the home-pointer file
# that installer writes, then both documented install homes. Looking in fewer
# places than the vendor writes to is what makes a present lms read as absent
# and re-runs a multi-minute download on every install.
_resolve_lms_binary() {
    local candidate
    candidate="$(command -v lms 2>/dev/null)"
    if [ -n "$candidate" ]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    local lmstudio_home="$HOME/.lmstudio"
    if [ -f "$HOME/.lmstudio-home-pointer" ]; then
        lmstudio_home="$(cat "$HOME/.lmstudio-home-pointer")"
    fi

    for candidate in "$lmstudio_home/bin/lms" "$HOME/.lmstudio/bin/lms" "$HOME/.cache/lm-studio/bin/lms"; do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# Ensure the llmster background service (the lms CLI + daemon) is installed.
# Detected via the lms binary; installed silently from the official script if absent.
_ensure_llmster_installed() {
    local lms_binary
    if lms_binary="$(_resolve_lms_binary)"; then
        print_info "llmster (lms) already installed ($lms_binary)"
        return 0
    fi
    print_info "Installing llmster background service..."
    if curl -fsSL https://lmstudio.ai/install.sh | bash >> "$LOG_FILE" 2>&1; then
        print_success "llmster installed"
    else
        print_warning "Failed to install llmster (see $LOG_FILE)"
    fi
}

_maybe_install_cask() {
    local cask="$1"
    local prompt_text="$2"
    local app_name="$3"
    if brew list --cask "$cask" &> /dev/null; then
        print_info "$cask cask already installed"
        return 1
    fi
    if [ -n "$app_name" ] && [ -d "/Applications/${app_name}.app" ]; then
        print_info "$app_name already installed (found in /Applications)"
        return 1
    fi
    if [ "$NON_INTERACTIVE" = true ] || [ ! -t 0 ]; then
        print_info "Skipping optional $cask cask during an unattended install"
        return 1
    fi
    if ! confirm "$prompt_text" "n"; then
        return 1
    fi
    print_info "Installing $cask via brew cask..."
    if brew install --cask "$cask" >> "$LOG_FILE" 2>&1; then
        print_success "$cask installed"
        return 0
    fi
    print_warning "Failed to install $cask cask (see $LOG_FILE)"
    return 1
}

# Install or update Claude Code
install_claude_code() {
    if command -v claude &> /dev/null; then
        CLAUDE_VERSION=$(claude --version 2>&1 || echo "unknown")
        print_info "Claude Code already installed ($CLAUDE_VERSION)"
        update_agent_cli "Claude Code" claude update
        return 0
    fi

    print_info "Installing Claude Code via the native installer..."
    local install_ok=0
    curl -fsSL https://claude.ai/install.sh > /tmp/claude_install.sh 2>> "$LOG_FILE" || install_ok=1
    if [ $install_ok -eq 0 ]; then
        _run_agent_cli_installer bash /tmp/claude_install.sh >> "$LOG_FILE" 2>&1 || install_ok=2
    fi
    if [ $install_ok -eq 0 ]; then
        print_success "Claude Code installed"
    else
        print_warning "Failed to install Claude Code (see $LOG_FILE)"
        print_info "You can install manually: curl -fsSL https://claude.ai/install.sh | bash"
    fi
}

setup_dsh_integration() {
    # The runtime, the TUI and every profile plugin move only through the DeepSeek stack
    # convergence: it picks the newest set in which everything installed fits, verifies it and
    # restores the previous set when verification fails. The global hooks.json is written later
    # by configure_agent_cli.
    if ! _run_agent_cli_installer sh "$INSTALL_DIR/teleclaude/install/dsh_plugins_checkout.sh" >> "$LOG_FILE" 2>&1; then
        print_warning "Could not ensure the dsh plugins checkout (see $LOG_FILE)"
    fi
    print_info "Converging the DeepSeek Harness stack..."
    local report
    local convergence_status=0
    report=$(PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" -m teleclaude.install.deepseek_stack </dev/null 2>&1) || convergence_status=$?
    echo "$report"
    log "DeepSeek stack convergence report: $report"
    case "$convergence_status" in
        0) print_success "DeepSeek Harness stack is converged" ;;
        2) print_warning "DeepSeek Harness stack was rolled back to the previous set (see the report above)" ;;
        3) print_error "DeepSeek Harness stack rollback is incomplete (see the report above)" ;;
        *) print_warning "DeepSeek Harness stack convergence changed nothing (see the report above)" ;;
    esac
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
                _run_sudo "refresh apt package lists before installing uv" apt-get update -qq &&
                _run_sudo "install uv with apt-get" apt-get install -y uv
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

    local uv_tool_bin
    if ! uv_tool_bin=$(uv tool dir --bin 2>> "$LOG_FILE"); then
        print_error "Could not resolve uv's tool bin directory; check the uv installation and re-run make install"
        exit 1
    fi
    if [ -n "$uv_tool_bin" ] && [ "$uv_tool_bin" != "$HOME/.local/bin" ]; then
        export PATH="$uv_tool_bin:$PATH"
    fi

    # Baseline sync installs core deps only: platform markers select the right
    # packages for any platform, and uv sync never pulls an extra. The
    # TTS-exclusive deps live in the `tts` extra, provisioned on demand the first
    # time TTS is enabled (uv sync --frozen --extra tts), not at setup time.
    print_info "Syncing Python environment with uv..."
    # A release is built from its lock and never edited: a sync that rewrote the lock would dirty it.
    if [ "$CI_MODE" = true ] || is_installation_release; then
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

converge_plumbing() {
    PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" -m teleclaude.project_setup.plumbing --plumbing-only "$INSTALL_DIR"
}

# Exit statuses the convergence entrypoint publishes (EXIT_STATUSES in
# teleclaude/entrypoints/docs_layout_convergence.py): 0 when every repository is
# settled, DOCS_LAYOUT_EXIT_HELD when some are blocked for their owner or deferred
# and none failed, and any other non-zero status for a failure.
DOCS_LAYOUT_EXIT_HELD=3
DOCS_LAYOUT_CONVERGENCE_FAILED=false

# A hold or deferral warns and the install completes; a failure is recorded and
# fails the install where it would print its completion banner, so the stages that
# do not depend on other repositories still run.
converge_docs_layout() {
    local status=0
    PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" -m teleclaude.entrypoints.docs_layout_convergence || status=$?
    if [ "$status" -eq 0 ]; then
        return 0
    fi
    if [ "$status" -eq "$DOCS_LAYOUT_EXIT_HELD" ]; then
        print_warning "Documentation layout convergence left repositories blocked for their owner or deferred (report above); install continues"
        return 0
    fi
    print_error "Documentation layout convergence failed (report above); the install fails after its remaining stages"
    DOCS_LAYOUT_CONVERGENCE_FAILED=true
}

fail_install_on_convergence_failure() {
    if [ "$DOCS_LAYOUT_CONVERGENCE_FAILED" = true ]; then
        print_header "Install Failed"
        print_error "Documentation layout convergence failed (report above)"
        log "Install failed: documentation layout convergence"
        return 1
    fi
}

install_voice_bridge() {
    VOICE_BRIDGE_DIR="$INSTALL_DIR/teleclaude/adapters/discord/voice_bridge"
    if [ -d "$VOICE_BRIDGE_DIR" ]; then
        print_info "Installing and building Discord voice bridge..."
        if (
            set -e
            cd "$VOICE_BRIDGE_DIR"
            ulimit -n 4096
            corepack pnpm install --frozen-lockfile
            corepack pnpm build
        ) >> "$LOG_FILE" 2>&1; then
            print_success "Discord voice bridge installed and built"
        else
            print_error "Failed to install or build Discord voice bridge"
            exit 1
        fi
    fi
}

install_deps_only() {
    print_header "Installing Project Dependencies"

    if ! command -v uv >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi

    (cd "$INSTALL_DIR" && uv run --group dev python -c "print(\"Python environment ready\")")

    check_node
    setup_corepack
    setup_prettier
    install_voice_bridge

    converge_plumbing
    converge_docs_layout
    print_success "Project dependencies installed"
}

# Pinned Blueprint engine. Graphify ships daily; pin exactly so the graph.json
# contract the blueprint depends on stays stable (local/projects/teleclaude/adr/0016).
GRAPHIFY_PINNED_VERSION="0.9.84"

# Full transitive dependency closure, version-pinned with SHA256 hashes
# (generated by `uv pip compile --generate-hashes --universal` from
# graphifyy==$GRAPHIFY_PINNED_VERSION). Regenerate this lock whenever the pinned
# version changes. Every runtime wheel is hash-verified before execution; no
# transitive dependency is resolved live from the index.
GRAPHIFY_LOCK_FILE="$INSTALL_DIR/graphifyy-$GRAPHIFY_PINNED_VERSION.requirements.txt"

# ── Canonical CLI publish location ────────────────────────────────────────────
# Every platform CLI (telec, graphify) publishes to one
# OS-agnostic location: ~/.local/bin. The daemon and all agent shells guarantee
# it on PATH (local/projects/teleclaude/spec/agent-shell-path), so it always resolves. We create it
# if missing and never scatter binaries to brew/usr-local.
TELEC_BIN_DIR="$HOME/.local/bin"
_TELEC_PATH_PROMPTED=0

# publish_binary <name> <source>: idempotently link <source> to
# $TELEC_BIN_DIR/<name>, and transparently migrate our own stale copies out of
# other PATH dirs. Only removes a symlink that resolves to <source> — a foreign
# binary of the same name is never touched. Pure filesystem work, no prompts,
# safe to re-run. The PATH offer is a separate one-shot (_ensure_local_bin_on_path)
# called once from main().
publish_binary() {
    local name="$1" source="$2"
    local canonical="$TELEC_BIN_DIR/$name"
    mkdir -p "$TELEC_BIN_DIR"

    local d other
    for d in /opt/homebrew/bin /usr/local/bin; do
        other="$d/$name"
        if [ -L "$other" ] && [ "$(readlink "$other")" = "$source" ]; then
            if ! rm -f "$other" 2>/dev/null; then
                _run_sudo "remove TeleClaude's stale $name link from $d" rm -f "$other" || return 1
            fi
            print_info "Migrated $name out of $d into $TELEC_BIN_DIR"
        fi
    done

    if [ "$(readlink "$canonical" 2>/dev/null)" != "$source" ]; then
        ln -sfn "$source" "$canonical"
    fi
}

# _ensure_local_bin_on_path: one-shot. If $TELEC_BIN_DIR is not on the user's
# PATH, present a guarded snippet and — only when running interactively — offer
# to inject it into the detected shell rc. Under --yes/--ci (NON_INTERACTIVE) it
# prints the snippet and continues without blocking. The only approval gate in
# the install; everything else is transparent.
_ensure_local_bin_on_path() {
    [ "$_TELEC_PATH_PROMPTED" = 1 ] && return 0
    _TELEC_PATH_PROMPTED=1
    case ":$PATH:" in *":$TELEC_BIN_DIR:"*) return 0 ;; esac

    local rc
    case "$(basename "${SHELL:-sh}")" in
        zsh) rc="$HOME/.zshrc" ;;
        bash) rc="$HOME/.bashrc" ;;
        *) rc="$HOME/.profile" ;;
    esac
    if [ -f "$rc" ] && grep -qF '.local/bin' "$rc" 2>/dev/null; then
        return 0
    fi

    local line
    line="case \":\$PATH:\" in *\":\$HOME/.local/bin:\"*) ;; *) export PATH=\"\$HOME/.local/bin:\$PATH\" ;; esac"
    print_warning "$TELEC_BIN_DIR is not on your PATH — TeleClaude CLIs won't resolve in new shells."
    printf '  Suggested addition to %s:\n' "$rc"
    printf '    # TeleClaude: resolve user-published CLIs (telec, graphify)\n'
    printf '    %s\n' "$line"
    if [ "$NON_INTERACTIVE" = false ] && [ -t 0 ]; then
        printf '  Append it to %s now? [Y/n] ' "$rc"
        local ans
        read -r ans
        case "$ans" in
            [Nn]*) print_info "Skipped — add the line above, then open a new shell." ; return 0 ;;
        esac
        printf '\n# TeleClaude: resolve user-published CLIs (telec, graphify)\n%s\n' "$line" >> "$rc"
        print_success "Added ~/.local/bin to PATH in $rc — open a new shell to apply."
    else
        print_info "Add the line above to $rc, then open a new shell."
    fi
}

# Install the Blueprint engine (graphify) so it is on PATH on every agent machine.
# Graphify is synced into a dedicated managed venv from the hash lock and the
# verified executable is symlinked onto PATH.
install_blueprint_engine() {
    print_header "Installing Blueprint Engine"

    if [ ! -f "$GRAPHIFY_LOCK_FILE" ]; then
        print_error "Missing Graphify hash lock: $GRAPHIFY_LOCK_FILE"
        exit 1
    fi

    local graphify_venv="$TELECLAUDE_HOME/tools/graphify/$GRAPHIFY_PINNED_VERSION"
    local graphify_bin="$graphify_venv/bin/graphify"

    # Skip only when the pinned version is already present in the managed venv —
    # an arbitrary graphify already on PATH is never trusted.
    if [ -x "$graphify_bin" ] && [ "$("$graphify_bin" --version 2>/dev/null | awk '{print $2}')" = "$GRAPHIFY_PINNED_VERSION" ]; then
        if [ "$CI_MODE" = false ]; then
            publish_binary graphify "$graphify_bin" || exit 1
        fi
        print_info "Blueprint engine (graphify $GRAPHIFY_PINNED_VERSION) already installed"
        return 0
    fi

    print_info "Installing blueprint engine graphifyy==$GRAPHIFY_PINNED_VERSION from hash-locked requirements..."

    local ok=0
    mkdir -p "$(dirname "$graphify_venv")"
    # Drop any stale/partial venv from an aborted prior run; uv venv refuses to
    # write into a pre-existing non-venv directory, which wedges self-hosted
    # runners that carry state across jobs.
    rm -rf "$graphify_venv"
    uv venv "$graphify_venv" --python "$PYTHON_CMD" >> "$LOG_FILE" 2>&1 || ok=1
    if [ $ok -eq 0 ]; then
        uv pip sync "$GRAPHIFY_LOCK_FILE" \
            --python "$graphify_venv/bin/python" \
            --require-hashes \
            --only-binary :all: \
            --strict >> "$LOG_FILE" 2>&1 || ok=2
    fi

    if [ $ok -ne 0 ]; then
        print_error "Failed to install blueprint engine graphifyy==$GRAPHIFY_PINNED_VERSION; make install cannot provision codebase Blueprint support (see $LOG_FILE)"
        exit 1
    fi

    local installed
    installed=$("$graphify_bin" --version 2>/dev/null | awk '{print $2}')
    if [ "$installed" != "$GRAPHIFY_PINNED_VERSION" ]; then
        print_error "Installed graphify version mismatch — expected $GRAPHIFY_PINNED_VERSION, got ${installed:-unknown}"
        exit 1
    fi

    if [ "$CI_MODE" = true ]; then
        print_info "CI: graphify ready at $graphify_bin (not published to ~/.local/bin)"
    else
        publish_binary graphify "$graphify_bin"
    fi
    print_success "Blueprint engine installed (graphify $GRAPHIFY_PINNED_VERSION)"
}

# Package that owns the shared instrukt-ai-logs / instrukt-ai-log-setup
# entrypoints. Never version-pinned — this is a shared machine-global CLI,
# per third-party/uv/tool-management, and tracks latest.
LOG_RUNTIME_PACKAGE="instruktai-python-logger"
LOG_RUNTIME_ENTRYPOINT="instrukt-ai-logs"

# Detect a conflicting entrypoint owner, then ensure the logging package is
# present and current. Split from install_log_runtime below so these two legs
# can be rehearsed against an isolated UV_TOOL_DIR/UV_TOOL_BIN_DIR without
# reaching the setup entrypoint's real host-global writes (rotation conf,
# launchd agent/systemd timer).
# Returns 0 to proceed to setup, 2 when a declined conflict already warned and
# setup must be skipped, 1 on any other ensure failure.
_log_runtime_ensure_current() {
    local conflict_owner
    conflict_owner=$(uv tool list 2>/dev/null | awk -v ep="$LOG_RUNTIME_ENTRYPOINT" -v pkg="$LOG_RUNTIME_PACKAGE" '
        /^- / { if ($2 == ep && owner != pkg) print owner; next }
        { owner = $1 }
    ' || true)
    if [ -n "$conflict_owner" ]; then
        print_warning "$conflict_owner already publishes the $LOG_RUNTIME_ENTRYPOINT entrypoint (uv tool list) and may resolve a stale log root; TeleClaude will not remove it. Run 'uv tool uninstall $conflict_owner', then re-run make install."
    fi

    if uv tool install --upgrade "$LOG_RUNTIME_PACKAGE" >> "$LOG_FILE" 2>&1; then
        return 0
    fi

    if [ -n "$conflict_owner" ]; then
        print_warning "Logging runtime left unwired — resolve the entrypoint conflict above and re-run make install."
        return 2
    fi
    print_error "Failed to install/upgrade $LOG_RUNTIME_PACKAGE (see $LOG_FILE)"
    return 1
}

# Provision the machine's logging runtime: ensure the InstruktAI logger CLI is
# present and current, then delegate the machine-level wiring to the
# package's own idempotent setup entrypoint rather than reimplementing it. A
# declined conflict (above) warns and leaves make install successful; any
# other failure to install, upgrade, or wire the runtime fails the install,
# because this step has just taken responsibility for a runtime the operator
# is told to read from immediately after install (see README quickstart).
install_log_runtime() {
    print_header "Installing Logging Runtime"

    local ensure_rc=0
    _log_runtime_ensure_current || ensure_rc=$?
    if [ "$ensure_rc" -eq 2 ]; then
        return 0
    elif [ "$ensure_rc" -ne 0 ]; then
        exit 1
    fi

    local setup_report
    if setup_report=$(instrukt-ai-log-setup 2>&1); then
        echo "$setup_report"
        print_success "Logging runtime wired"
    else
        echo "$setup_report" >> "$LOG_FILE"
        print_error "Failed to run instrukt-ai-log-setup (see $LOG_FILE)"
        exit 1
    fi
}

# Install global telec CLI symlink
install_global_cli() {
    if [ "$CI_MODE" = true ]; then
        return 0
    fi
    print_header "Installing Global CLI (telec)"

    publish_binary telec "$LIVE_ROOT/bin/telec"
    print_success "Installed telec at $TELEC_BIN_DIR/telec"
}

# Check that the macOS launcher compiler is present before installation work.
preflight_macos() {
    if [ "$OS" != "macos" ]; then
        return 0
    fi
    print_header "macOS Preflight"

    local blockers=0
    if /usr/bin/xcrun --find swiftc > /dev/null 2>&1; then
        print_info "Xcode Command Line Tools present (swiftc)"
    else
        print_error "Xcode Command Line Tools are missing — the launcher apps cannot be compiled."
        echo "        YOU MUST RUN:  xcode-select --install"
        echo "        It opens a macOS installer dialog; rerun 'make install' when it finishes."
        blockers=$((blockers + 1))
    fi

    if [ "$blockers" -gt 0 ]; then
        print_error "Preflight found $blockers item(s) only you can resolve. Nothing was changed."
        exit 1
    fi
    print_success "Preflight clear"
}

run_macos_setup_action() {
    local action="$1"
    shift
    if [ "$OS" != "macos" ]; then
        return 0
    fi

    local cmd=(env "PYTHONPATH=$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" "-m" "teleclaude.entrypoints.macos_setup" "--project-root" "$INSTALL_DIR")
    cmd+=("$@")
    cmd+=("$action")

    "${cmd[@]}"
}

run_macos_launcher_identity() {
    if [ "$OS" != "macos" ]; then
        return 0
    fi
    if ! PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" -m teleclaude.install.launcher_identity \
        --intent converge --project-root "$INSTALL_DIR"; then
        print_error "Launcher signing and installation failed"
        exit 1
    fi
}

install_macos_tmux_server() {
    if [ "$OS" != "macos" ]; then
        return 0
    fi
    print_header "Installing macOS tmux Server Service"
    # Every maintenance run holds the drain marker (teleclaude/core/integration/maintenance_trigger.py);
    # it deploys no changed tmux definition and reloads no running server.
    local setup_flags=()
    if [ "${TELECLAUDE_MAINTENANCE_DRAIN_HELD:-}" = "1" ]; then
        setup_flags+=(--defer-changes)
    fi
    if run_macos_setup_action "install-tmux-server" ${setup_flags[@]+"${setup_flags[@]}"}; then
        print_success "tmux server service installed"
    else
        print_error "Failed to install tmux server service"
        exit 1
    fi
}

# Full Disk Access is the one grant macOS will not let an installer give itself,
# so the probe's verdict becomes the closing instruction rather than a warning
# buried above the completion banner.
run_macos_permissions_probe() {
    if [ "$OS" != "macos" ]; then
        return 0
    fi
    if run_macos_setup_action "permissions-probe"; then
        print_success "Full Disk Access already granted for the tested paths"
        return 0
    fi

    print_header "Remaining Manual Step: Full Disk Access"
    echo "The launcher apps cannot read your protected files yet. macOS only"
    echo "accepts this grant from you directly:"
    echo ""
    echo "  1. Open System Settings > Privacy & Security > Full Disk Access"
    echo "  2. Add each app below with the plus button"
    echo "  3. Quit and reopen anything already running under them"
    echo ""
    local app_name
    for app_name in "$HOME"/Applications/*Launcher.app; do
        [ -d "$app_name" ] && echo "     $app_name"
    done
    echo ""
    echo "If an entry is already listed but access still fails, remove it with the"
    echo "minus button and add it again — a stale row keeps showing as enabled."
}

validate_config() {
    print_header "Validating config.yml"
    local output
    local exit_code=0
    output=$(PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" -m teleclaude.entrypoints.config_validation 2>&1) || exit_code=$?
    if [ -n "$output" ]; then
        printf '%s\n' "$output"
    fi
    if [ "$exit_code" -eq 0 ]; then
        print_success "config.yml is valid"
    else
        # Unattended installs discard stdout/stderr, so the log is the only
        # durable record of which check failed and why.
        log "ERROR: config validate exited $exit_code with output:"
        printf '%s\n' "$output" >> "$LOG_FILE"
        print_error "config.yml validation failed — fix the errors above and re-run install"
        exit 1
    fi
}

# Exit status the migration entrypoint publishes (ExitStatus in teleclaude/config/migrations/_run.py)
# when it withheld the run because the running daemon cannot read the current configuration version and
# no document failed.
CONFIG_MIGRATION_EXIT_WITHHELD=3

# A withheld run warns and the install continues: the documents stay at their stored version and the
# stages after this one read them through the in-memory migration. Any other non-zero status is a failure.
migrate_config_documents() {
    print_header "Migrating configuration documents"
    local status=0
    PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" -m teleclaude.config.migrations --trigger install || status=$?
    if [ "$status" -eq 0 ]; then
        print_success "Configuration documents are current"
    elif [ "$status" -eq "$CONFIG_MIGRATION_EXIT_WITHHELD" ]; then
        print_warning "Configuration documents stay at their stored version while the running daemon's migration reach is lower; a later migration run stores them (report above); install continues"
    else
        print_error "Configuration document migration failed — fix the errors above and re-run install"
        exit 1
    fi
}

discard_declaration_views() {
    print_header "Discarding cached declaration views"
    if PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" -m teleclaude.entrypoints.declaration_view discard --trigger install; then
        print_success "Cached declaration views discarded"
    else
        print_error "Declaration view discard failed — fix the errors above and re-run install"
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

activate_home_repository() {
    PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/bin/init/activate_home_repository.py"
}

run_owner_establishment() {
    local operation="$1"
    if ! PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" -m teleclaude.core.reconciliation.owner_establishment "$operation"; then
        print_error "Owner establishment $operation failed; fix the reported cause and re-run make install"
        exit 1
    fi
}

setup_local_redis() {
    if ! PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" -m teleclaude.install.local_redis; then
        print_error "The local Redis could not be set up; fix the reported cause and re-run make install"
        exit 1
    fi
}

run_environment_defaults() {
    if ! PYTHONPATH="$INSTALL_DIR" "$INSTALL_DIR/.venv/bin/python" -m teleclaude.entrypoints.environment_defaults; then
        print_error "Local environment defaults could not be written; fix the reported cause and re-run make install"
        exit 1
    fi
}

# Load modular install steps
# shellcheck source=/dev/null
source "$INSTALL_DIR/bin/init/redis_locality.sh"
# shellcheck source=/dev/null
source "$INSTALL_DIR/bin/init/setup_mcp_config.sh"
# shellcheck source=/dev/null
source "$INSTALL_DIR/bin/init/link_shared_scripts.sh"
# shellcheck source=/dev/null
source "$INSTALL_DIR/bin/init/install_services.sh"

# Main
main() {
    parse_args "$@"
    select_install_mode
    export PATH="$HOME/.local/bin:$PATH"

    print_header "TeleClaude Install"
    log "Install started in $INSTALL_DIR"

    if [ "$DEPS_ONLY_MODE" = true ]; then
        run_install_stage install_deps_only install_deps_only
        fail_install_on_convergence_failure
        print_header "Install Complete"
        print_success "Project dependencies installed"
        log "Deps-only install completed"
        return 0
    fi

    run_install_stage detect_os detect_os
    if [ "$CI_MODE" = false ]; then
        run_install_stage preflight_macos preflight_macos
    fi
    run_install_stage check_python check_python
    run_install_stage check_node check_node

    run_install_stage install_system_deps install_system_deps
    run_install_stage install_python_deps install_python_deps
    if [ "$CI_MODE" = false ]; then
        run_install_stage owner_decide run_owner_establishment decide
        run_install_stage run_environment_defaults run_environment_defaults
        run_install_stage setup_local_redis setup_local_redis
    fi
    run_install_stage ensure_config_yml ensure_config_yml
    run_install_stage install_blueprint_engine install_blueprint_engine
    if [ "$CI_MODE" = false ]; then
        run_install_stage install_log_runtime install_log_runtime
    fi
    run_install_stage setup_corepack setup_corepack
    run_install_stage setup_prettier setup_prettier
    run_install_stage install_voice_bridge install_voice_bridge
    # Agent CLI enablement/install resolves from config and can invoke external
    # installers against the host; CI never needs it (this repository has no
    # test lane that exercises it).
    if [ "$CI_MODE" = false ]; then
        run_install_stage setup_agents_interactive setup_agents_interactive
    fi
    run_install_stage ensure_teleclaude_yaml ensure_teleclaude_yaml
    run_install_stage migrate_config_documents migrate_config_documents
    run_install_stage discard_declaration_views discard_declaration_views
    # A checkout verifying its configuration in CI needs it valid. A release's convergence does not: the
    # configuration is completed afterwards, in the terminal interface or with `telec config`, so `telec`
    # is published before any configuration is required.
    if [ "$CI_MODE" = true ]; then
        run_install_stage validate_config validate_config
    fi
    run_install_stage install_global_cli install_global_cli
    run_install_stage _ensure_local_bin_on_path _ensure_local_bin_on_path
    if [ "$CI_MODE" = false ]; then
        run_install_stage owner_establish run_owner_establishment establish
    fi

    # Services are deployed and the daemon started by `telec app start` once the configuration is valid,
    # and the release's documentation, agent artifacts and schemas are published by the install act.
    if [ "$CI_MODE" = false ]; then
        run_install_stage run_macos_launcher_identity run_macos_launcher_identity
        run_install_stage install_macos_tmux_server install_macos_tmux_server
        run_install_stage withdraw_docs_watch_service withdraw_docs_watch_service
    fi

    run_install_stage setup_mcp_config setup_mcp_config
    if [ "$CI_MODE" = false ]; then
        run_install_stage configure_agent_cli configure_agent_cli
        run_install_stage activate_home_repository activate_home_repository
    fi
    run_install_stage converge_plumbing converge_plumbing
    if [ "$CI_MODE" = false ]; then
        run_install_stage converge_docs_layout converge_docs_layout
        run_install_stage link_shared_scripts link_shared_scripts
    fi

    fail_install_on_convergence_failure
    print_header "Install Complete"
    print_success "Binaries, Python dependencies, and machine-global tooling installed"

    if [ "$CI_MODE" = false ]; then
        run_install_stage run_macos_permissions_probe run_macos_permissions_probe
    fi

    log "Install completed"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
