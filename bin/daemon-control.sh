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
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Configuration
PID_FILE="$PROJECT_ROOT/teleclaude.pid"
LOG_FILE="/var/log/instrukt-ai/teleclaude/teleclaude.log"

# Platform-specific config
if [[ "$OSTYPE" == "darwin"* ]]; then
    PLATFORM="macos"
    SERVICE_LABEL="ai.instrukt.teleclaude.daemon"
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

# Wait for daemon to come up with retries
# Args: max_attempts (default 10), old_pid (optional - wait for this PID to die first)
# Returns 0 if daemon started with new PID, 1 if timeout
wait_for_daemon() {
    local max_attempts=${1:-10}
    local old_pid=${2:-""}
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if [ "$PLATFORM" = "macos" ]; then
            # Avoid `ps`/process enumeration (can be blocked by macOS sandboxes).
            # Consider the daemon "up" once the MCP socket exists and accepts a connection.
            local socket_path="/tmp/teleclaude.sock"
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

        if [ $attempt -lt $max_attempts ]; then
            log_info "Waiting for daemon to start (attempt $attempt/$max_attempts)..."
            sleep 1
        fi
        attempt=$((attempt + 1))
    done
    return 1
}

# Check if service is loaded/enabled
is_service_loaded() {
    if [ "$PLATFORM" = "macos" ]; then
        # `launchctl list` can be unreliable/sandboxed; `print` is more robust.
        launchctl print "gui/$(id -u)/$SERVICE_LABEL" >/dev/null 2>&1
    else
        systemctl is-enabled "$SERVICE_LABEL" >/dev/null 2>&1
    fi
}

# Start daemon via service manager
start_daemon() {
    log_info "Starting TeleClaude daemon via $PLATFORM service manager..."

    # Verify service file exists
    if [ ! -f "$SERVICE_PATH" ]; then
        log_error "Service file not found at $SERVICE_PATH"
        log_error "Run 'make init' first to set up the service"
        exit 1
    fi

    if [ "$PLATFORM" = "macos" ]; then
        local domain="gui/$(id -u)"
        # Load service if not loaded
        if ! is_service_loaded; then
            log_info "Loading launchd service..."
            # Prefer bootstrap on modern macOS; fallback to load for older versions.
            launchctl bootstrap "$domain" "$SERVICE_PATH" 2>/dev/null || launchctl load "$SERVICE_PATH"
        else
            log_info "Service already loaded, kickstarting..."
            launchctl kickstart -k "$domain/$SERVICE_LABEL" 2>/dev/null || true
        fi
    else
        # Linux: enable and start systemd service
        log_info "Enabling and starting systemd service..."
        sudo systemctl enable "$SERVICE_LABEL"
        sudo systemctl start "$SERVICE_LABEL"
    fi

    # Wait for daemon to come up (up to 10 seconds)
    if wait_for_daemon 10; then
        PID=$(cat "$PID_FILE")
        log_info "Daemon started successfully (PID: $PID)"
        log_info "Service manager will auto-restart if killed"
        return 0
    fi

    # If not running after retries, check why
    if is_service_loaded; then
        log_error "Service loaded but daemon not running after 10 seconds"
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

    if ! is_service_loaded; then
        log_warn "Service not loaded"
        return 0
    fi

    if [ "$PLATFORM" = "macos" ]; then
        # macOS: bootout from launchd (unloads the job)
        local domain="gui/$(id -u)"
        log_info "Booting out launchd service..."
        launchctl bootout "$domain" "$SERVICE_PATH" 2>/dev/null || launchctl unload "$SERVICE_PATH" 2>/dev/null || true
        sleep 1
    else
        # Linux: stop and disable systemd service
        log_info "Stopping and disabling systemd service..."
        sudo systemctl stop "$SERVICE_LABEL"
        sudo systemctl disable "$SERVICE_LABEL"
        sleep 1
    fi

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

    # Check if service is loaded
    if ! is_service_loaded; then
        log_warn "Service NOT loaded/enabled"
        log_warn "Run 'make start' to start the service"
        return 1
    fi

    log_info "Service: LOADED"

    # Check service manager status
    if [ "$PLATFORM" = "macos" ]; then
        local domain="gui/$(id -u)"
        SERVICE_PRINT=$(launchctl print "$domain/$SERVICE_LABEL" 2>/dev/null || true)
        if [ -n "$SERVICE_PRINT" ]; then
            STATE=$(echo "$SERVICE_PRINT" | awk -F' = ' '/^[[:space:]]*state[[:space:]]*=/{print $2; exit}')
            PID=$(echo "$SERVICE_PRINT" | awk -F' = ' '/^[[:space:]]*pid[[:space:]]*=/{print $2; exit}')
            LAST_EXIT=$(echo "$SERVICE_PRINT" | awk -F' = ' '/^[[:space:]]*last exit code[[:space:]]*=/{print $2; exit}')
            log_info "launchd state: ${STATE:-unknown} (pid: ${PID:-unknown}, last_exit: ${LAST_EXIT:-unknown})"
            if [ -n "$STATE" ] && [ "$STATE" != "running" ]; then
                log_warn "Service state is not running: $STATE"
                return 1
            fi
        else
            log_warn "Unable to query launchd job details (launchctl print returned nothing)"
        fi
    else
        SERVICE_STATUS=$(systemctl is-active "$SERVICE_LABEL" 2>/dev/null || echo "inactive")
        log_info "systemctl status: $SERVICE_STATUS"
        if [ "$SERVICE_STATUS" != "active" ]; then
            log_error "Service is not active: $SERVICE_STATUS"
            return 1
        fi
    fi

    # Component health checks (sockets + API reads)
    MCP_SOCKET="/tmp/teleclaude.sock"
    API_SOCKET="/tmp/teleclaude-api.sock"
    overall_ok=0

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
        if command -v curl >/dev/null 2>&1; then
            local status
            status=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 1 --max-time 1 --unix-socket "$socket_path" "http://localhost${endpoint}") || status=""
            if [ "$status" = "200" ]; then
                echo "ok"
            else
                echo "fail"
            fi
            return 0
        fi
        python3 - <<PY 2>/dev/null
import socket, sys
path = "$socket_path"
endpoint = "$endpoint"
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
    first = data.split(b\"\\r\\n\", 1)[0].decode(\"utf-8\", \"ignore\")
    if \" 200 \" in first or first.endswith(\" 200\"):
        print(\"ok\")
    else:
        print(\"fail\")
except Exception:
    print(\"fail\")
PY
    }

    # MCP socket health
    if [ -S "$MCP_SOCKET" ] && command -v python3 >/dev/null 2>&1; then
        MCP_HEALTH=$(check_unix_socket "$MCP_SOCKET" || true)
        if [ "$MCP_HEALTH" = "ok" ]; then
            log_info "MCP socket: HEALTHY ($MCP_SOCKET)"
        elif [ "$MCP_HEALTH" = "blocked" ]; then
            log_warn "MCP socket: UNKNOWN (blocked by environment)"
        else
            log_warn "MCP socket: NOT responding"
            overall_ok=1
        fi
    else
        log_warn "MCP socket: MISSING ($MCP_SOCKET)"
        overall_ok=1
    fi

    # API socket health + read checks
    if [ -S "$API_SOCKET" ] && command -v python3 >/dev/null 2>&1; then
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
            API_READ=$(check_api_endpoint "$API_SOCKET" "/computers" || true)
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
        log_info "Daemon health: HEALTHY (all components responding)"
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
        local domain="gui/$(id -u)"
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
        local domain="gui/$(id -u)"
        KICKSTART_OUT=$(launchctl kickstart -k "$domain/$SERVICE_LABEL" 2>&1) || {
            log_error "launchctl kickstart failed: $KICKSTART_OUT"
            return 1
        }

        # PID may remain unchanged on some macOS restarts; verify via health instead.
        NEW_PID=$(launchctl print "$domain/$SERVICE_LABEL" 2>/dev/null | awk -F' = ' '/^[[:space:]]*pid[[:space:]]*=/{print $2; exit}' || true)
        if [ -n "$OLD_PID" ] && [ -n "$NEW_PID" ] && [ "$NEW_PID" = "$OLD_PID" ]; then
            log_warn "launchctl kickstart pid unchanged ($NEW_PID); verifying health"
        fi
    else
        sudo systemctl restart "$SERVICE_LABEL"
    fi

    # Wait for daemon to come up (up to 10 seconds)
    if wait_for_daemon 10 "$OLD_PID"; then
        if [ "$PLATFORM" = "macos" ]; then
            PID=$(launchctl print "gui/$(id -u)/$SERVICE_LABEL" 2>/dev/null | awk -F' = ' '/^[[:space:]]*pid[[:space:]]*=/{print $2; exit}' || true)
        fi
        if [ -z "${PID:-}" ] && [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
        fi
        log_info "Daemon restarted successfully (PID: ${PID:-unknown})"
        EXIT_CODE=0
    else
        log_error "Restart failed. Try: make kill to hard kill the daemon. You may have to stop the mcp process separately."
        EXIT_CODE=1
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
        OLD_PID=$(launchctl print "gui/$(id -u)/$SERVICE_LABEL" 2>/dev/null | awk -F' = ' '/^[[:space:]]*pid[[:space:]]*=/{print $2; exit}' || true)
        if [ -z "$OLD_PID" ]; then
            log_warn "Could not determine daemon PID via launchctl"
            return 1
        fi
        log_info "Killing daemon via launchd (PID: $OLD_PID)..."
        launchctl kill SIGKILL "gui/$(id -u)/$SERVICE_LABEL" 2>/dev/null || true
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

    # Wait for service manager to auto-restart (up to 10 seconds)
    if wait_for_daemon 10 "$OLD_PID"; then
        log_info "Daemon auto-restarted by service manager"
        return 0
    fi

    log_error "Service manager didn't auto-restart. Check: make status"
    return 1
}

# Main command dispatcher
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
    *)
        echo "Usage: $0 {start|stop|restart|kill|status}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the daemon"
        echo "  stop    - Stop the daemon (disables service)"
        echo "  restart - Restart the daemon"
        echo "  kill    - Kill daemon (service auto-restarts)"
        echo "  status  - Check daemon status"
        exit 1
        ;;
esac
