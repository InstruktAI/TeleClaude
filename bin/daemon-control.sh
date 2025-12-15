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
LOG_FILE="/var/log/teleclaude.log"

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
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            # If old_pid specified, skip if PID file still has old value
            if [ -n "$old_pid" ] && [ "$PID" = "$old_pid" ]; then
                : # continue waiting for new PID
            elif ps -p "$PID" > /dev/null 2>&1; then
                return 0
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
        launchctl list | grep -q "$SERVICE_LABEL"
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
        # Load service if not loaded
        if ! is_service_loaded; then
            log_info "Loading launchd service..."
            launchctl load "$SERVICE_PATH"
        else
            log_info "Service already loaded, kickstarting..."
            launchctl kickstart -k "gui/$(id -u)/$SERVICE_LABEL" 2>/dev/null || true
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
        log_error "Check logs: tail -50 $LOG_FILE"
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
        # macOS: unload from launchd
        log_info "Unloading launchd service..."
        launchctl unload "$SERVICE_PATH" 2>/dev/null || true
        sleep 1
    else
        # Linux: stop and disable systemd service
        log_info "Stopping and disabling systemd service..."
        sudo systemctl stop "$SERVICE_LABEL"
        sudo systemctl disable "$SERVICE_LABEL"
        sleep 1
    fi

    # Clean up any remaining processes
    if pgrep -f "teleclaude.daemon" > /dev/null; then
        log_warn "Daemon still running, force killing..."
        pkill -9 -f "teleclaude.daemon" 2>/dev/null || true
        sleep 1
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
        SERVICE_STATUS=$(launchctl list | grep "$SERVICE_LABEL" || true)
        log_info "launchctl status: $SERVICE_STATUS"

        # Parse launchctl output: PID STATUS LABEL
        # STATUS is the exit code - 0 means running normally, non-zero means last exit was abnormal
        EXIT_CODE=$(echo "$SERVICE_STATUS" | awk '{print $2}')
        if [ -n "$EXIT_CODE" ] && [ "$EXIT_CODE" != "0" ] && [ "$EXIT_CODE" != "-" ]; then
            if [ "$EXIT_CODE" = "42" ]; then
                log_info "Last exit code: 42 (deployment restart)"
            else
                log_warn "Last exit code: $EXIT_CODE (process may have crashed previously)"
                if [ "$EXIT_CODE" = "-9" ]; then
                    log_warn "Last instance was killed (SIGKILL)"
                fi
            fi
        fi
    else
        SERVICE_STATUS=$(systemctl is-active "$SERVICE_LABEL" 2>/dev/null || echo "inactive")
        log_info "systemctl status: $SERVICE_STATUS"
        if [ "$SERVICE_STATUS" != "active" ]; then
            log_error "Service is not active: $SERVICE_STATUS"
            return 1
        fi
    fi

    # Check if process is running
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            # Get process uptime
            if command -v ps >/dev/null; then
                UPTIME=$(ps -p "$PID" -o etime= | tr -d ' ')
            else
                UPTIME="unknown"
            fi

            log_info "Daemon process: RUNNING (PID: $PID, uptime: $UPTIME)"

            # Check health via socket connection
            SOCKET_PATH="/tmp/teleclaude.sock"
            if command -v python3 >/dev/null 2>&1; then
                HEALTH_CHECK=$(python3 -c "
import socket
import sys
try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2)
    s.connect('$SOCKET_PATH')
    s.close()
    print('ok')
except Exception:
    sys.exit(1)
" 2>/dev/null || echo "")
                if [ "$HEALTH_CHECK" = "ok" ]; then
                    log_info "Daemon health: HEALTHY (MCP socket responding)"
                else
                    log_warn "Daemon health: MCP socket not responding"
                fi
            else
                log_info "Daemon health: UNKNOWN (python3 not available)"
            fi
            return 0
        else
            log_warn "PID file exists but process $PID NOT running"
        fi
    else
        log_warn "Daemon process: NOT RUNNING (no PID file)"
    fi

    log_warn "Daemon appears to be down. Check logs: tail -50 $LOG_FILE"
    return 1
}

# Restart daemon via service manager
restart_daemon() {
    log_info "Restarting TeleClaude daemon..."

    OLD_PID=""
    if [ -f "$PID_FILE" ]; then
        OLD_PID=$(cat "$PID_FILE")
        if ps -p "$OLD_PID" > /dev/null 2>&1; then
            log_info "Killing daemon process (PID: $OLD_PID)..."
            kill "$OLD_PID" 2>/dev/null || true
        fi
    fi

    # Use service manager restart (reliable and fast)
    if [ "$PLATFORM" = "macos" ]; then
        launchctl kickstart -k "gui/$(id -u)/$SERVICE_LABEL" 2>/dev/null || true
    else
        sudo systemctl restart "$SERVICE_LABEL"
    fi

    # Wait for daemon to come up (up to 10 seconds)
    if wait_for_daemon 10 "$OLD_PID"; then
        PID=$(cat "$PID_FILE")
        log_info "Daemon restarted successfully (PID: $PID)"
        EXIT_CODE=0
    else
        log_error "Restart failed. Try: make kill to hard kill the daemon. You may have to stop the mcp process separately."
        EXIT_CODE=1
    fi

    # Return immediately with collected exit code
    return $EXIT_CODE
}

# Kill daemon process (service manager will auto-restart)
kill_daemon() {
    log_info "Killing daemon process (service will auto-restart)..."

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

    # Wait for service manager to auto-restart (up to 10 seconds)
    if wait_for_daemon 10 "$OLD_PID"; then
        NEW_PID=$(cat "$PID_FILE")
        if [ "$NEW_PID" != "$OLD_PID" ]; then
            log_info "Daemon auto-restarted by service manager (new PID: $NEW_PID)"
        else
            log_info "Daemon restarted (PID: $NEW_PID)"
        fi
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
