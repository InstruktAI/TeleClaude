#!/usr/bin/env bash
# TeleClaude Daemon Control Script
# Cross-platform wrapper for daemon lifecycle management
#
# Supports:
# - macOS: launchd
# - Linux: systemd
#
# The service manager (launchd/systemd) is the ONLY thing that starts/stops
# the daemon process. This ensures KeepAlive/Restart works for auto-restart.

set -e

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

# Configuration
PID_FILE="$PROJECT_ROOT/teleclaude.pid"
LOG_FILE="/var/log/instrukt-ai/teleclaude/teleclaude.log"
API_SOCKET="/tmp/teleclaude-api.sock"
# Startup soft warning threshold in seconds. Startup keeps waiting past this
# threshold and emits warnings instead of failing hard.
STARTUP_WAIT_SECONDS="${TELECLAUDE_DAEMON_STARTUP_WAIT_S:-15}"
STARTUP_STREAM_PID=""

# Platform-specific config
if [[ "$OSTYPE" == "darwin"* ]]; then
    PLATFORM="macos"
    V1_DAEMON_LABEL="ai.instrukt.teleclaude.daemon"
    TELEC_DAEMON_LABEL="ai.instrukt.teleclaude.telec-daemon"
    DOCS_WATCH_LABEL="ai.instrukt.teleclaude.docs-watch"
    SERVICE_LABEL="$V1_DAEMON_LABEL"
    SERVICE_PATH="$HOME/Library/LaunchAgents/$SERVICE_LABEL.plist"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    PLATFORM="linux"
    SERVICE_LABEL="teleclaude"
    SERVICE_PATH="/etc/systemd/system/$SERVICE_LABEL.service"
else
    echo "Unsupported platform: $OSTYPE"
    exit 1
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

launchd_domain() {
    printf 'gui/%s\n' "$(id -u)"
}

launchd_path_env() {
    local launchd_path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

    if [ -d "/opt/homebrew/bin" ]; then
        launchd_path="/opt/homebrew/bin:$launchd_path"
    fi
    if [ -d "/usr/local/bin" ]; then
        launchd_path="/usr/local/bin:$launchd_path"
    fi

    printf '%s\n' "$launchd_path" | tr ':' '\n' | awk '!seen[$0]++' | tr '\n' ':' | sed 's/:$//'
}

launchd_plist_path() {
    local label="$1"
    printf '%s/Library/LaunchAgents/%s.plist\n' "$HOME" "$label"
}

managed_launchd_labels() {
    printf '%s\n' "$V1_DAEMON_LABEL"
    printf '%s\n' "$TELEC_DAEMON_LABEL"
    printf '%s\n' "$DOCS_WATCH_LABEL"
}

unit_name() {
    case "$1" in
        "$V1_DAEMON_LABEL")
            printf 'v1 daemon'
            ;;
        "$TELEC_DAEMON_LABEL")
            printf 'telec-daemon'
            ;;
        "$DOCS_WATCH_LABEL")
            printf 'docs-watch'
            ;;
        *)
            printf '%s' "$1"
            ;;
    esac
}

normalize_required_config_path() {
    local raw_path="$1"
    case "$raw_path" in
        "~")
            printf '%s\n' "$HOME"
            ;;
        "~/"*)
            printf '%s/%s\n' "$HOME" "${raw_path#~/}"
            ;;
        /*)
            printf '%s\n' "$raw_path"
            ;;
        *)
            printf '%s/%s\n' "$PROJECT_ROOT" "$raw_path"
            ;;
    esac
}

require_config_files() {
    local env_path="${TELECLAUDE_ENV_PATH:-$PROJECT_ROOT/.env}"
    local config_path="${TELECLAUDE_CONFIG_PATH:-${TELECLAUDE_HOME:-$HOME/.teleclaude}/config.yml}"
    local normalized_env_path
    local normalized_config_path
    normalized_env_path="$(normalize_required_config_path "$env_path")"
    normalized_config_path="$(normalize_required_config_path "$config_path")"

    if [ ! -f "$normalized_env_path" ] || [ ! -f "$normalized_config_path" ]; then
        echo 'run `telec config wizard`'
        exit 1
    fi
}

extract_log_message() {
    printf '%s\n' "$1" | sed -n 's/.*msg="\([^"]*\)".*/\1/p'
}

install_systemd_service() {
    local service_name="teleclaude"
    local service_file="/etc/systemd/system/${service_name}.service"
    local path_file="/etc/systemd/system/${service_name}-config.path"

    # Create wrapper script for SSH agent support
    log_info "Creating daemon wrapper script..."
    cat > "$PROJECT_ROOT/bin/teleclaude-wrapper.sh" <<'EOF'
#!/bin/bash
# Resolve project root from this script location so it works under systemd.
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Source keychain SSH agent environment
if [ -f ~/.keychain/$(hostname)-sh ]; then
    source ~/.keychain/$(hostname)-sh
fi
# Execute daemon
exec $PROJECT_ROOT/.venv/bin/python -m teleclaude.daemon
EOF
    chmod +x "$PROJECT_ROOT/bin/teleclaude-wrapper.sh"
    log_info "Created daemon wrapper script"

    # Create service file
    log_info "Creating systemd service..."

    sudo tee "$service_file" > /dev/null <<EOF
[Unit]
Description=TeleClaude Terminal Bridge Daemon
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_ROOT
Environment="PATH=$PROJECT_ROOT/.venv/bin:/usr/local/bin:/usr/bin:/bin"
# SSH_AUTH_SOCK sourced from keychain in wrapper
ExecStart=$PROJECT_ROOT/bin/teleclaude-wrapper.sh
Restart=on-failure
RestartSec=10
LimitNOFILE=4096
StandardOutput=null
StandardError=null
KillMode=process

[Install]
WantedBy=multi-user.target
EOF

    log_info "Created systemd service file"

    # Create path unit to watch config.yml and restart on changes
    log_info "Creating config watcher..."

    sudo tee "$path_file" > /dev/null <<EOF
[Unit]
Description=TeleClaude Config File Watcher

[Path]
PathModified=$PROJECT_ROOT/config.yml
Unit=${service_name}.service

[Install]
WantedBy=multi-user.target
EOF

    log_info "Created config watcher"

    # Reload systemd
    sudo systemctl daemon-reload

    # Enable service and path watcher
    log_info "Enabling service to start on boot..."
    sudo systemctl enable "$service_name"
    sudo systemctl enable "${service_name}-config.path"
    log_info "Service enabled"

    # Start service and path watcher
    log_info "Starting service..."
    sudo systemctl start "$service_name"
    sudo systemctl start "${service_name}-config.path"

    sleep 2

    # Check status
    if sudo systemctl is-active --quiet "$service_name"; then
        log_info "Service started successfully"
        log_info "Service commands:"
        log_info "  Status:  sudo systemctl status $service_name"
        log_info "  Stop:    sudo systemctl stop $service_name"
        log_info "  Restart: sudo systemctl restart $service_name"
        log_info "  Logs:    sudo journalctl -u $service_name -f"
    else
        log_error "Service failed to start"
        log_info "Check logs: sudo journalctl -u $service_name -n 50"
        exit 1
    fi
}

install_systemd_docs_watch_service() {
    local service_name="teleclaude-docs-watch"
    local service_file="/etc/systemd/system/${service_name}.service"
    local template_file="$PROJECT_ROOT/templates/teleclaude-docs-watch.service"
    local command="uv run --quiet --project $PROJECT_ROOT -m teleclaude.cli.watch"
    local service_path="$PROJECT_ROOT/.venv/bin:/usr/local/bin:/usr/bin:/bin"

    log_info "Creating global docs watcher systemd service..."

    if [ ! -f "$template_file" ]; then
        log_error "Template file not found: $template_file"
        exit 1
    fi

    local service_content
    service_content=$(sed \
        -e "s|{{COMMAND}}|$command|g" \
        -e "s|{{WORKING_DIR}}|$PROJECT_ROOT|g" \
        -e "s|{{USER}}|$USER|g" \
        -e "s|{{PATH}}|$service_path|g" \
        "$template_file")

    printf '%s\n' "$service_content" | sudo tee "$service_file" > /dev/null
    log_info "Created docs watcher systemd service file"

    sudo systemctl daemon-reload
    sudo systemctl enable "$service_name"
    sudo systemctl restart "$service_name"
}

install_launchd_service() {
    local service_name="$V1_DAEMON_LABEL"
    local plist_file
    plist_file="$(launchd_plist_path "$service_name")"
    local template_file="$PROJECT_ROOT/templates/ai.instrukt.teleclaude.daemon.plist"

    # Create LaunchAgents directory if needed
    mkdir -p "$HOME/Library/LaunchAgents"

    # Create plist file from template
    log_info "Creating launchd service from template..."

    if [ ! -f "$template_file" ]; then
        log_error "Template file not found: $template_file"
        exit 1
    fi

    local launchd_path
    launchd_path="$(launchd_path_env)"

    # Generate plist from template
    sed -e "s|{{PYTHON_PATH}}|$PROJECT_ROOT/.venv/bin/python|g" \
        -e "s|{{WORKING_DIR}}|$PROJECT_ROOT|g" \
        -e "s|{{PATH}}|$launchd_path|g" \
        "$template_file" > "$plist_file"

    log_info "Created launchd plist file"

    # Load service
    log_info "Loading service..."
    local domain
    domain="$(launchd_domain)"
    # Prefer modern launchctl bootstrap; fall back to legacy load for older macOS.
    launchctl bootout "$domain" "$plist_file" 2>/dev/null || launchctl unload "$plist_file" 2>/dev/null || true
    if ! launchctl bootstrap "$domain" "$plist_file" 2>/dev/null; then
        launchctl load "$plist_file"
    fi

    sleep 2

    # Check if running
    if launchctl print "$domain/$service_name" >/dev/null 2>&1; then
        log_info "Service loaded successfully"
        log_info "Service commands:"
        log_info "  Status:  launchctl print $domain/$service_name"
        log_info "  Stop:    launchctl bootout $domain $plist_file"
        log_info "  Start:   launchctl bootstrap $domain $plist_file"
        log_info "  Logs:    instrukt-ai-logs teleclaude --since 5m"
    else
        log_error "Service failed to load"
        log_info "Check logs: instrukt-ai-logs teleclaude --since 5m"
        exit 1
    fi
}

install_launchd_telec_daemon_service() {
    local service_name="$TELEC_DAEMON_LABEL"
    local plist_file
    plist_file="$(launchd_plist_path "$service_name")"
    local template_file="$PROJECT_ROOT/templates/ai.instrukt.teleclaude.telec-daemon.plist"
    local binary_path="${TELEC_DAEMON_BINARY:-$HOME/.local/bin/telec-daemon}"

    mkdir -p "$HOME/Library/LaunchAgents"

    log_info "Creating telec-daemon launchd service from template..."

    if [ ! -f "$template_file" ]; then
        log_error "Template file not found: $template_file"
        exit 1
    fi

    if [ ! -x "$binary_path" ]; then
        log_warn "telec-daemon binary not found or not executable: $binary_path"
        log_info "Run bin/install.sh or install target/release/telec-daemon to $binary_path"
        return 0
    fi

    local launchd_path
    launchd_path="$(launchd_path_env)"

    sed -e "s|{{BINARY_PATH}}|$binary_path|g" \
        -e "s|{{WORKING_DIR}}|$PROJECT_ROOT|g" \
        -e "s|{{PATH}}|$launchd_path|g" \
        "$template_file" > "$plist_file"

    log_info "Created telec-daemon plist file"

    log_info "Loading telec-daemon service..."
    local domain
    domain="$(launchd_domain)"
    launchctl bootout "$domain" "$plist_file" 2>/dev/null || launchctl unload "$plist_file" 2>/dev/null || true
    if ! launchctl bootstrap "$domain" "$plist_file" 2>/dev/null; then
        launchctl load "$plist_file"
    fi
}

install_launchd_docs_watch_service() {
    local service_name="$DOCS_WATCH_LABEL"
    local plist_file
    plist_file="$(launchd_plist_path "$service_name")"
    local template_file="$PROJECT_ROOT/templates/ai.instrukt.teleclaude.docs-watch.plist"

    mkdir -p "$HOME/Library/LaunchAgents"

    log_info "Creating global docs watcher launchd service from template..."

    if [ ! -f "$template_file" ]; then
        log_error "Template file not found: $template_file"
        exit 1
    fi

    local launchd_path
    launchd_path="$(launchd_path_env)"

    local command="uv run --quiet --project $PROJECT_ROOT -m teleclaude.cli.watch"

    sed -e "s|{{LABEL}}|$service_name|g" \
        -e "s|{{COMMAND}}|$command|g" \
        -e "s|{{WORKING_DIR}}|$PROJECT_ROOT|g" \
        -e "s|{{PATH}}|$launchd_path|g" \
        "$template_file" > "$plist_file"

    log_info "Created docs watcher plist file"

    log_info "Loading docs watcher service..."
    local domain
    domain="$(launchd_domain)"
    launchctl bootout "$domain" "$plist_file" 2>/dev/null || launchctl unload "$plist_file" 2>/dev/null || true
    if ! launchctl bootstrap "$domain" "$plist_file" 2>/dev/null; then
        launchctl load "$plist_file"
    fi
}

install_service() {
    log_info "Installing System Service"

    case "$PLATFORM" in
        linux)
            install_systemd_service
            install_systemd_docs_watch_service
            ;;
        macos)
            install_launchd_service
            install_launchd_telec_daemon_service
            install_launchd_docs_watch_service
            ;;
    esac
}

start_startup_log_stream() {
    if [ ! -r "$LOG_FILE" ]; then
        return 0
    fi

    tail -n 0 -F "$LOG_FILE" 2>/dev/null | while IFS= read -r line; do
        case "$line" in
            *"[STARTUP]"*|*"Lifecycle startup completed"*|*"Daemon startup was slow"* )
                message=$(extract_log_message "$line")
                if [ -n "$message" ]; then
                    log_info "$message"
                fi
                ;;
        esac
    done &
    STARTUP_STREAM_PID=$!
}

stop_startup_log_stream() {
    if [ -n "$STARTUP_STREAM_PID" ]; then
        kill "$STARTUP_STREAM_PID" >/dev/null 2>&1 || true
        wait "$STARTUP_STREAM_PID" 2>/dev/null || true
        STARTUP_STREAM_PID=""
    fi
}

# Wait for daemon to come up
# Args: old_pid (optional - wait for this PID to die first)
# Returns 0 if daemon started with new PID/socket, 1 if service unloaded
wait_for_daemon() {
    local old_pid=${1:-""}
    local attempt=1
    local next_warn_after=$STARTUP_WAIT_SECONDS

    log_info "Waiting for API socket. Expected startup time is usually 10-25s."

    while true; do
        if [ "$PLATFORM" = "macos" ]; then
            # Avoid `ps`/process enumeration (can be blocked by macOS sandboxes).
            # Consider the daemon "up" once the API socket exists and accepts a connection.
            local socket_path="$API_SOCKET"
            if [ -S "$socket_path" ]; then
                if command -v python3 >/dev/null 2>&1; then
                    # If the current environment is sandboxed and cannot connect to the socket,
                    # treat PermissionError as "up" (the daemon may still be healthy).
                    if python3 -c "
import socket
import sys
try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.2)
    s.connect('$socket_path')
    s.close()
    sys.exit(0)
except PermissionError:
    sys.exit(0)
except Exception:
    sys.exit(1)
" >/dev/null 2>&1; then
                        return 0
                    fi
                else
                    # Best-effort: socket exists, but we can't actively probe it.
                    return 0
                fi
            fi
        else
            if [ -f "$PID_FILE" ]; then
                PID=$(cat "$PID_FILE")
                # If old_pid specified, skip if PID file still has old value
                if [ -n "$old_pid" ] && [ "$PID" = "$old_pid" ]; then
                    : # continue waiting for new PID
                elif ps -p "$PID" > /dev/null 2>&1; then
                    return 0
                fi
            fi
        fi

        if ! is_service_loaded; then
            return 1
        fi

        if [ "$attempt" -ge "$next_warn_after" ]; then
            log_warn "Daemon startup is taking longer than expected (${attempt}s elapsed). Still waiting..."
            next_warn_after=$((next_warn_after + STARTUP_WAIT_SECONDS))
        elif [ $((attempt % 5)) -eq 0 ]; then
            log_info "Still waiting for daemon startup (${attempt}s elapsed)..."
        fi

        sleep 1
        attempt=$((attempt + 1))
    done
}

# Check if service is loaded/enabled
is_service_loaded() {
    if [ "$PLATFORM" = "macos" ]; then
        # `launchctl list` can be unreliable/sandboxed; `print` is more robust.
        is_launchd_unit_loaded "$SERVICE_LABEL"
    else
        systemctl is-enabled "$SERVICE_LABEL" >/dev/null 2>&1
    fi
}

is_launchd_unit_loaded() {
    local label="$1"
    launchctl print "$(launchd_domain)/$label" >/dev/null 2>&1
}

ensure_launchd_managed_plists() {
    local label
    while IFS= read -r label; do
        if [ ! -f "$(launchd_plist_path "$label")" ]; then
            install_service
            return 0
        fi
    done < <(managed_launchd_labels)
}

start_launchd_unit() {
    local label="$1"
    local plist_file
    plist_file="$(launchd_plist_path "$label")"
    local domain
    domain="$(launchd_domain)"

    if [ ! -f "$plist_file" ]; then
        install_service
    fi

    if [ ! -f "$plist_file" ] && [ "$label" = "$TELEC_DAEMON_LABEL" ]; then
        log_warn "$(unit_name "$label"): plist not installed; skipping until telec-daemon is installed"
        return 0
    fi

    if [ "$label" = "$TELEC_DAEMON_LABEL" ]; then
        local binary_path="${TELEC_DAEMON_BINARY:-$HOME/.local/bin/telec-daemon}"
        if [ ! -x "$binary_path" ]; then
            log_warn "$(unit_name "$label"): binary not installed at $binary_path; skipping unit"
            return 0
        fi
    fi

    if is_launchd_unit_loaded "$label"; then
        log_info "$(unit_name "$label"): already loaded"
        return 0
    fi

    log_info "$(unit_name "$label"): loading launchd service"
    launchctl bootstrap "$domain" "$plist_file" 2>/dev/null || launchctl load "$plist_file"
}

stop_launchd_unit() {
    local label="$1"
    local plist_file
    plist_file="$(launchd_plist_path "$label")"
    local domain
    domain="$(launchd_domain)"

    if ! is_launchd_unit_loaded "$label"; then
        log_warn "$(unit_name "$label"): service not loaded"
        return 0
    fi

    log_info "$(unit_name "$label"): booting out launchd service"
    launchctl bootout "$domain" "$plist_file" 2>/dev/null || launchctl unload "$plist_file" 2>/dev/null || true
}

restart_launchd_unit() {
    local label="$1"
    local domain
    domain="$(launchd_domain)"

    if ! is_launchd_unit_loaded "$label"; then
        start_launchd_unit "$label"
        return
    fi

    log_info "$(unit_name "$label"): kickstarting launchd service"
    launchctl kickstart -k "$domain/$label" 2>/dev/null || true
}

status_launchd_unit() {
    local label="$1"
    local domain
    domain="$(launchd_domain)"
    local service_print
    service_print=$(launchctl print "$domain/$label" 2>/dev/null || true)

    if [ -z "$service_print" ]; then
        log_warn "$(unit_name "$label"): NOT loaded"
        return 1
    fi

    local state
    local pid
    local last_exit
    state=$(echo "$service_print" | awk -F' = ' '/^[[:space:]]*state[[:space:]]*=/{print $2; exit}')
    pid=$(echo "$service_print" | awk -F' = ' '/^[[:space:]]*pid[[:space:]]*=/{print $2; exit}')
    last_exit=$(echo "$service_print" | awk -F' = ' '/^[[:space:]]*last exit code[[:space:]]*=/{print $2; exit}')
    log_info "$(unit_name "$label"): ${state:-unknown} (pid: ${pid:-unknown}, last_exit: ${last_exit:-unknown})"

    if [ -n "$state" ] && [ "$state" != "running" ]; then
        return 1
    fi
    return 0
}

# Start daemon via service manager
start_daemon() {
    require_config_files

    log_info "Starting TeleClaude daemon via $PLATFORM service manager..."

    if [ "$PLATFORM" = "macos" ]; then
        ensure_launchd_managed_plists
    elif [ ! -f "$SERVICE_PATH" ]; then
        install_service
    fi

    start_startup_log_stream

    if [ "$PLATFORM" = "macos" ]; then
        local domain
        domain="$(launchd_domain)"
        # Load service if not loaded
        if ! is_service_loaded; then
            log_info "Loading launchd service..."
            # Prefer bootstrap on modern macOS; fallback to load for older versions.
            launchctl bootstrap "$domain" "$SERVICE_PATH" 2>/dev/null || launchctl load "$SERVICE_PATH"
        else
            log_info "Service already loaded, kickstarting..."
            launchctl kickstart -k "$domain/$SERVICE_LABEL" 2>/dev/null || true
        fi
        start_launchd_unit "$TELEC_DAEMON_LABEL"
        start_launchd_unit "$DOCS_WATCH_LABEL"
    else
        # Linux: enable and start systemd service
        log_info "Enabling and starting systemd service..."
        sudo systemctl enable "$SERVICE_LABEL"
        sudo systemctl start "$SERVICE_LABEL"
    fi

    # Wait for daemon to come up. This uses a soft warning threshold rather than
    # a hard timeout because adapter startup can legitimately exceed 15 seconds.
    if wait_for_daemon; then
        stop_startup_log_stream
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            log_info "Daemon started successfully (PID: $PID)"
        else
            log_info "Daemon started successfully (API socket responding)"
        fi
        log_info "Service manager will auto-restart if killed"
        return 0
    fi

    stop_startup_log_stream

    # If the service unloaded before the API socket came up, surface that immediately.
    if is_service_loaded; then
        log_error "Service loaded but daemon never exposed a healthy API socket"
        if [ "$PLATFORM" = "macos" ]; then
            log_error "Check status: launchctl list | grep teleclaude"
        else
            log_error "Check status: sudo systemctl status teleclaude"
        fi
        log_error "Check logs: instrukt-ai-logs teleclaude --since 5m"
    else
        log_error "Failed to load service"
    fi
    return 1
}

# Stop daemon via service manager
stop_daemon() {
    log_info "Stopping TeleClaude daemon..."

    if [ "$PLATFORM" = "macos" ]; then
        stop_launchd_unit "$DOCS_WATCH_LABEL"
        stop_launchd_unit "$TELEC_DAEMON_LABEL"
        stop_launchd_unit "$SERVICE_LABEL"
        sleep 1
        if [ -f "$PID_FILE" ]; then
            rm -f "$PID_FILE"
        fi
        log_info "Managed launchd units stopped"
        return 0
    fi

    if ! is_service_loaded; then
        log_warn "Service not loaded"
        return 0
    fi

    # Linux: stop and disable systemd service
    log_info "Stopping and disabling systemd service..."
    sudo systemctl stop "$SERVICE_LABEL"
    sudo systemctl disable "$SERVICE_LABEL"
    sleep 1

    # Clean up any remaining processes (Linux only; macOS process enumeration may be restricted)
    if [ "$PLATFORM" != "macos" ]; then
        if pgrep -f "teleclaude.daemon" > /dev/null; then
            log_warn "Daemon still running, force killing..."
            pkill -9 -f "teleclaude.daemon" 2>/dev/null || true
            sleep 1
        fi
    fi

    # Clean up PID file
    if [ -f "$PID_FILE" ]; then
        rm -f "$PID_FILE"
    fi

    log_info "Daemon stopped (service unloaded)"
}

# Check daemon status
status_daemon() {
    log_info "Checking daemon status ($PLATFORM)..."

    overall_ok=0
    v1_loaded=1

    # Check if service is loaded
    if ! is_service_loaded; then
        log_warn "v1 daemon: NOT loaded/enabled"
        log_warn "Run 'make start' to start the service"
        overall_ok=1
        v1_loaded=0
    elif [ "$PLATFORM" = "macos" ]; then
        status_launchd_unit "$SERVICE_LABEL" || overall_ok=1
    else
        log_info "Service: LOADED"
    fi

    if [ "$PLATFORM" = "macos" ]; then
        # telec-daemon (v2 Rust) is required-if-present until the v2 cutover:
        # an installed unit must be healthy; an absent unit is informational.
        if [ -f "$HOME/Library/LaunchAgents/$TELEC_DAEMON_LABEL.plist" ]; then
            status_launchd_unit "$TELEC_DAEMON_LABEL" || overall_ok=1
        else
            log_info "telec-daemon (v2, pre-cutover): not installed — OK"
        fi
        status_launchd_unit "$DOCS_WATCH_LABEL" || overall_ok=1
    fi

    # Check service manager status
    if [ "$PLATFORM" != "macos" ]; then
        SERVICE_STATUS=$(systemctl is-active "$SERVICE_LABEL" 2>/dev/null || echo "inactive")
        log_info "systemctl status: $SERVICE_STATUS"
        if [ "$SERVICE_STATUS" != "active" ]; then
            log_error "Service is not active: $SERVICE_STATUS"
            return 1
        fi
    fi

    # Component health checks (API socket + API reads)
    check_unix_socket() {
        local socket_path="$1"
        python3 - <<PY 2>/dev/null
import socket, sys
path = "$socket_path"
try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.5)
    s.connect(path)
    s.close()
    print("ok")
except PermissionError:
    print("blocked")
except Exception:
    print("fail")
PY
    }

    check_api_endpoint() {
        local socket_path="$1"
        local endpoint="$2"
        local accepted_codes="${3:-200}"
        if command -v curl >/dev/null 2>&1; then
            local status
            status=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 1 --max-time 1 --unix-socket "$socket_path" "http://localhost${endpoint}") || status=""
            case ",$accepted_codes," in
                *",$status,"*)
                    echo "ok"
                    ;;
                *)
                    echo "fail"
                    ;;
            esac
            return 0
        fi
        python3 - <<PY 2>/dev/null
import socket
path = "$socket_path"
endpoint = "$endpoint"
accepted = {code.strip() for code in "$accepted_codes".split(",") if code.strip()}
try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1.0)
    s.connect(path)
    req = f"GET {endpoint} HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n"
    s.sendall(req.encode("utf-8"))
    data = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    s.close()
    first = data.split(b"\\r\\n", 1)[0].decode("utf-8", "ignore")
    parts = first.split()
    status_code = parts[1] if len(parts) >= 2 else ""
    if status_code in accepted:
        print("ok")
    else:
        print("fail")
except Exception:
    print("fail")
PY
    }

    # API socket health + read checks
    if [ "$v1_loaded" -eq 0 ]; then
        log_warn "Daemon health: SKIPPED (v1 daemon service not loaded)"
        overall_ok=1
    elif [ -S "$API_SOCKET" ] && command -v python3 >/dev/null 2>&1; then
        API_SOCKET_HEALTH=$(check_unix_socket "$API_SOCKET" || true)
        if [ "$API_SOCKET_HEALTH" = "ok" ]; then
            log_info "API socket: HEALTHY ($API_SOCKET)"
            API_HEALTH=$(check_api_endpoint "$API_SOCKET" "/health" || true)
            if [ "$API_HEALTH" = "ok" ]; then
                log_info "API /health: OK"
            else
                log_warn "API /health: FAIL"
                overall_ok=1
            fi
            API_READ=$(check_api_endpoint "$API_SOCKET" "/computers" "200,401,403" || true)
            if [ "$API_READ" = "ok" ]; then
                log_info "API read (/computers): OK"
            else
                log_warn "API read (/computers): FAIL"
                overall_ok=1
            fi
        else
            log_warn "API socket: UNHEALTHY ($API_SOCKET)"
            overall_ok=1
        fi
    else
        log_warn "API socket: MISSING ($API_SOCKET)"
        overall_ok=1
    fi

    if [ $overall_ok -eq 0 ]; then
        log_info "Daemon health: HEALTHY (API components responding)"
        return 0
    fi

    log_warn "Daemon health: DEGRADED. Check logs: instrukt-ai-logs teleclaude --since 5m"
    return 1
}

# Restart daemon via service manager
restart_daemon() {
    log_info "Restarting TeleClaude daemon..."

    OLD_PID=""
    if [ "$PLATFORM" = "macos" ]; then
        local domain
        domain="$(launchd_domain)"
        OLD_PID=$(launchctl print "$domain/$SERVICE_LABEL" 2>/dev/null | awk -F' = ' '/^[[:space:]]*pid[[:space:]]*=/{print $2; exit}' || true)
    elif [ -f "$PID_FILE" ]; then
        OLD_PID=$(cat "$PID_FILE")
        if ps -p "$OLD_PID" > /dev/null 2>&1; then
            log_info "Killing daemon process (PID: $OLD_PID)..."
            kill "$OLD_PID" 2>/dev/null || true
        fi
    fi

    # Use service manager restart (reliable and fast)
    if [ "$PLATFORM" = "macos" ]; then
        local domain
        domain="$(launchd_domain)"
        KICKSTART_OUT=$(launchctl kickstart -k "$domain/$SERVICE_LABEL" 2>&1) || {
            log_error "launchctl kickstart failed: $KICKSTART_OUT"
            return 1
        }
        restart_launchd_unit "$TELEC_DAEMON_LABEL"
        restart_launchd_unit "$DOCS_WATCH_LABEL"

        # PID may remain unchanged on some macOS restarts; verify via health instead.
        NEW_PID=$(launchctl print "$domain/$SERVICE_LABEL" 2>/dev/null | awk -F' = ' '/^[[:space:]]*pid[[:space:]]*=/{print $2; exit}' || true)
        if [ -n "$OLD_PID" ] && [ -n "$NEW_PID" ] && [ "$NEW_PID" = "$OLD_PID" ]; then
            log_warn "launchctl kickstart pid unchanged ($NEW_PID); verifying health"
        fi
    else
        sudo systemctl restart "$SERVICE_LABEL"
    fi

    # Wait for daemon to come up (up to STARTUP_WAIT_SECONDS)
    if wait_for_daemon "$OLD_PID"; then
        if [ "$PLATFORM" = "macos" ]; then
            PID=$(launchctl print "$(launchd_domain)/$SERVICE_LABEL" 2>/dev/null | awk -F' = ' '/^[[:space:]]*pid[[:space:]]*=/{print $2; exit}' || true)
        fi
        if [ -z "${PID:-}" ] && [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
        fi
        log_info "Daemon restarted successfully (PID: ${PID:-unknown})"
        EXIT_CODE=0
    else
        log_warn "Restart health check failed after kickstart; falling back to stop/start."
        if stop_daemon && start_daemon; then
            EXIT_CODE=0
        else
            log_error "Restart failed. Try: make kill to hard kill the daemon."
            EXIT_CODE=1
        fi
    fi

    # Always run a status check after restart
    if status_daemon; then
        return $EXIT_CODE
    fi
    return 1
}

# Kill daemon process (service manager will auto-restart)
kill_daemon() {
    log_info "Killing daemon process (service will auto-restart)..."

    OLD_PID=""
    if [ "$PLATFORM" = "macos" ]; then
        OLD_PID=$(launchctl print "$(launchd_domain)/$SERVICE_LABEL" 2>/dev/null | awk -F' = ' '/^[[:space:]]*pid[[:space:]]*=/{print $2; exit}' || true)
        if [ -z "$OLD_PID" ]; then
            log_warn "Could not determine daemon PID via launchctl"
            return 1
        fi
        log_info "Killing daemon via launchd (PID: $OLD_PID)..."
        launchctl kill SIGKILL "$(launchd_domain)/$SERVICE_LABEL" 2>/dev/null || true
        if is_launchd_unit_loaded "$TELEC_DAEMON_LABEL"; then
            log_info "Killing telec-daemon via launchd..."
            launchctl kill SIGKILL "$(launchd_domain)/$TELEC_DAEMON_LABEL" 2>/dev/null || true
        fi
    else
        if [ ! -f "$PID_FILE" ]; then
            log_warn "No PID file found"
            return 1
        fi

        OLD_PID=$(cat "$PID_FILE")
        if ! ps -p "$OLD_PID" > /dev/null 2>&1; then
            log_warn "Process $OLD_PID not running"
            return 1
        fi

        log_info "Killing daemon process (PID: $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
    fi

    # Wait for service manager to auto-restart (up to STARTUP_WAIT_SECONDS)
    if wait_for_daemon "$OLD_PID"; then
        log_info "Daemon auto-restarted by service manager"
        return 0
    fi

    log_error "Service manager didn't auto-restart. Check: make status"
    return 1
}

main() {
    cd "$PROJECT_ROOT"

    case "${1:-}" in
        start)
            start_daemon
            ;;
        stop)
            stop_daemon
            ;;
        restart)
            restart_daemon
            ;;
        kill)
            kill_daemon
            ;;
        status)
            status_daemon
            ;;
        install-telec-daemon)
            if [ "$PLATFORM" != "macos" ]; then
                log_info "telec-daemon launchd service install is macOS-only"
                exit 0
            fi
            install_launchd_telec_daemon_service
            ;;
        *)
            echo "Usage: $0 {start|stop|restart|kill|status|install-telec-daemon}"
            echo ""
            echo "Commands:"
            echo "  start   - Start the daemon"
            echo "  stop    - Stop the daemon (disables service)"
            echo "  restart - Restart the daemon"
            echo "  kill    - Kill daemon (service auto-restarts)"
            echo "  status  - Check daemon status"
            echo "  install-telec-daemon - Install and load the Rust runtime launchd unit"
            exit 1
            ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
