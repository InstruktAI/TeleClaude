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
if [ -n "${PROJECT_ROOT:-}" ]; then
    PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
else
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi
# Host services may only be controlled from the main checkout — only it carries
# the runtime .env, and a worktree-rooted service would pin host lifecycle to an
# ephemeral branch checkout. Linked worktrees live at <main>/trees/<name>:
# refuse, loudly, however PROJECT_ROOT was resolved (derived or explicit).
if [ "$(basename "$(dirname "$PROJECT_ROOT")")" = "trees" ]; then
    echo "[FATAL] daemon-control.sh invoked from a worktree ($PROJECT_ROOT). Controlling host services from a worktree is not allowed." >&2
    exit 1
fi

# Service definitions (labels, launchd resolvers, deploy primitive) live in
# install_services.sh, shared with bin/install.sh so the two cannot drift.
# shellcheck source=/dev/null
source "$SCRIPT_DIR/init/install_services.sh"

# Configuration
PID_FILE="$PROJECT_ROOT/teleclaude.pid"
LOG_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/instrukt-ai/teleclaude/teleclaude.log"
API_SOCKET="/tmp/teleclaude-api.sock"
# Startup soft warning threshold in seconds. Startup keeps waiting past this
# threshold and emits warnings instead of failing hard.
STARTUP_WAIT_SECONDS="${TELECLAUDE_DAEMON_STARTUP_WAIT_S:-15}"
# Bounded window for the configured Redis to connect at least once. A reachable
# Redis connects sub-second; exceeding this window means REDIS_URL is misconfigured
# or the server is unreachable, and `make start` reports failure.
REDIS_READY_WAIT_SECONDS="${TELECLAUDE_DAEMON_REDIS_READY_WAIT_S:-15}"
STOP_WAIT_SECONDS="${TELECLAUDE_DAEMON_STOP_WAIT_S:-25}"
STOP_KILL_WAIT_SECONDS="${TELECLAUDE_DAEMON_STOP_KILL_WAIT_S:-5}"
STARTUP_STREAM_PID=""

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

unit_name() {
    case "$1" in
        "$V1_DAEMON_LABEL")
            printf 'v1 daemon'
            ;;
        "$DOCS_WATCH_LABEL")
            printf 'docs-watch'
            ;;
        "$CRON_LABEL")
            printf 'cron'
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
    local env_path="$PROJECT_ROOT/.env"
    local config_path="${TELECLAUDE_HOME:-$HOME/.teleclaude}/config.yml"
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

launchd_unit_pid() {
    local label="$1"
    launchctl print "$(launchd_domain)/$label" 2>/dev/null | awk -F' = ' '/^[[:space:]]*pid[[:space:]]*=/{print $2; exit}' || true
}

systemd_main_pid() {
    systemctl show "$SERVICE_LABEL" --property=MainPID --value 2>/dev/null | awk '$1 != "0" { print $1; exit }' || true
}

is_pid_alive() {
    local pid="$1"
    [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1
}

pid_label() {
    local entry="$1"
    printf '%s\n' "${entry%%:*}"
}

pid_value() {
    local entry="$1"
    printf '%s\n' "${entry#*:}"
}

wait_for_daemon_death() {
    local timeout_seconds="$1"
    shift
    local entries=("$@")
    local deadline=$((SECONDS + timeout_seconds))
    local alive_entries=()
    local entry
    local label
    local pid

    while true; do
        alive_entries=()
        for entry in "${entries[@]}"; do
            label="$(pid_label "$entry")"
            pid="$(pid_value "$entry")"
            if [ -n "$pid" ] && is_pid_alive "$pid"; then
                alive_entries+=("$(unit_name "$label") pid $pid")
            fi
        done

        if [ "${#alive_entries[@]}" -eq 0 ]; then
            return 0
        fi

        if [ "$SECONDS" -ge "$deadline" ]; then
            log_warn "Still alive after ${timeout_seconds}s: ${alive_entries[*]}"
            return 1
        fi

        sleep 1
    done
}

kill_managed_pid() {
    local label="$1"
    local pid="$2"

    if [ -z "$pid" ] || ! is_pid_alive "$pid"; then
        return 0
    fi

    log_warn "$(unit_name "$label"): force killing pid $pid"
    if [ "$PLATFORM" = "macos" ]; then
        if is_launchd_unit_loaded "$label"; then
            launchctl kill SIGKILL "$(launchd_domain)/$label" 2>/dev/null || true
        fi
        if is_pid_alive "$pid"; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    else
        kill -9 "$pid" 2>/dev/null || true
    fi
}

is_managed_launchd_label() {
    local candidate="$1"
    local label
    while IFS= read -r label; do
        if [ "$candidate" = "$label" ]; then
            return 0
        fi
    done < <(managed_launchd_labels)
    return 1
}

installed_teleclaude_launchd_labels() {
    find \
        "$HOME/Library/LaunchAgents" \
        "/Library/LaunchAgents" \
        "/Library/LaunchDaemons" \
        -maxdepth 1 \
        -name 'ai.instrukt.teleclaude.*.plist' \
        -exec basename {} .plist \; 2>/dev/null | sort -u
}

check_managed_launchd_units_complete() {
    local unknown=0
    local label

    if [ "$PLATFORM" != "macos" ]; then
        return 0
    fi

    while IFS= read -r label; do
        [ -n "$label" ] || continue
        if ! is_managed_launchd_label "$label"; then
            log_warn "Unmanaged TeleClaude launchd unit installed: $label"
            unknown=1
        fi
    done < <(installed_teleclaude_launchd_labels)

    return "$unknown"
}

ensure_launchd_managed_plists() {
    # Content-gated: a no-op once every managed definition already matches.
    install_service
}

start_launchd_unit() {
    local label="$1"
    local plist_file
    plist_file="$(launchd_plist_path "$label")"
    local domain
    domain="$(launchd_domain)"

    # Content-gated: a no-op once the definition already matches.
    install_service

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

# Status check for a periodic (StartInterval) launchd unit. Unlike a continuous
# daemon, such a unit is loaded but idle between its scheduled runs, so a
# non-"running" state is healthy, not a failure. Reports loaded/unloaded and logs
# the last exit code informationally.
status_launchd_periodic_unit() {
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
    local last_exit
    state=$(echo "$service_print" | awk -F' = ' '/^[[:space:]]*state[[:space:]]*=/{print $2; exit}')
    last_exit=$(echo "$service_print" | awk -F' = ' '/^[[:space:]]*last exit code[[:space:]]*=/{print $2; exit}')
    log_info "$(unit_name "$label"): loaded (periodic; state: ${state:-idle}, last_exit: ${last_exit:-unknown})"
    return 0
}

# Poll an API endpoint over the unix socket; echo "ok" when the HTTP status is in
# the accepted set, "fail" otherwise. Shared by start (readiness gate) and status.
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

# Poll the readiness endpoint until Redis has connected at least once, or a bounded
# window elapses. Returns 0 on ready, 1 on timeout. The daemon is left running
# (the reconnect loop keeps retrying) — only the start invocation reports failure.
#
# On Linux the API socket binds well after wait_for_daemon returns (which gates on
# PID liveness alone), so socket-appearance must be folded into the wait: the
# readiness window only begins once the socket exists. A still-absent socket counts
# as "not ready yet, keep waiting" — never a silent pass.
wait_for_redis_ready() {
    # Phase 1: wait for the API socket to bind (adapter startup is usually 10-25s).
    local socket_deadline=$((SECONDS + STARTUP_WAIT_SECONDS * 3))
    while [ ! -S "$API_SOCKET" ]; do
        if ! is_service_loaded; then
            return 1
        fi
        if [ "$SECONDS" -ge "$socket_deadline" ]; then
            return 1
        fi
        sleep 1
    done

    # Phase 2: socket is up — poll /ready until Redis connects or the window elapses.
    # Without curl/python3 the probe can never report ok, so the window elapses to a
    # failure (fail-closed) rather than silently passing.
    local ready_deadline=$((SECONDS + REDIS_READY_WAIT_SECONDS))
    while [ "$SECONDS" -lt "$ready_deadline" ]; do
        if [ "$(check_api_endpoint "$API_SOCKET" "/ready" "200" || true)" = "ok" ]; then
            return 0
        fi
        sleep 1
    done
    return 1
}

# Start daemon via service manager
start_daemon() {
    require_config_files

    log_info "Starting TeleClaude daemon via $PLATFORM service manager..."

    if [ "$PLATFORM" = "macos" ]; then
        ensure_launchd_managed_plists
        check_managed_launchd_units_complete || return 1
    else
        # Content-gated: a no-op once every definition already matches.
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
        start_launchd_unit "$DOCS_WATCH_LABEL"
        # Load-only (not kickstart): a periodic StartInterval unit must be
        # loaded without forcing an off-schedule run on every start.
        start_launchd_unit "$CRON_LABEL"
    else
        # Linux: enable and start systemd service
        log_info "Enabling and starting systemd service..."
        sudo systemctl enable "$SERVICE_LABEL"
        sudo systemctl start "$SERVICE_LABEL"
        # install_service above already covers the full managed set
        # (content-gated); re-affirm the cron timer explicitly here too,
        # since it is the periodic unit most easily overlooked.
        install_systemd_cron_service
    fi

    # Wait for daemon to come up. This uses a soft warning threshold rather than
    # a hard timeout because adapter startup can legitimately exceed 15 seconds.
    if wait_for_daemon; then
        if ! wait_for_redis_ready; then
            stop_startup_log_stream
            log_error "Redis is unreachable: the daemon started but never connected to Redis within ${REDIS_READY_WAIT_SECONDS}s"
            log_error "Redis is a hard dependency. Verify REDIS_URL points to a reachable server, then re-run 'make start' (see 'telec config wizard')"
            return 1
        fi
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
    local pid_entries=()
    local label
    local pid
    local entry

    if [ "$PLATFORM" = "macos" ]; then
        while IFS= read -r label; do
            pid="$(launchd_unit_pid "$label")"
            pid_entries+=("$label:$pid")
        done < <(managed_launchd_labels)

        while IFS= read -r label; do
            stop_launchd_unit "$label"
        done < <(managed_launchd_labels)

        if ! wait_for_daemon_death "$STOP_WAIT_SECONDS" "${pid_entries[@]}"; then
            for entry in "${pid_entries[@]}"; do
                kill_managed_pid "$(pid_label "$entry")" "$(pid_value "$entry")"
            done
            wait_for_daemon_death "$STOP_KILL_WAIT_SECONDS" "${pid_entries[@]}"
        fi

        while IFS= read -r label; do
            if is_launchd_unit_loaded "$label"; then
                log_error "$(unit_name "$label"): still loaded after stop"
                return 1
            fi
        done < <(managed_launchd_labels)

        if [ -f "$PID_FILE" ]; then
            rm -f "$PID_FILE"
        fi
        log_info "Managed launchd units stopped and verified"
        return 0
    fi

    if ! is_service_loaded; then
        log_warn "Service not loaded"
        return 0
    fi

    pid="$(systemd_main_pid)"
    if [ -z "$pid" ] && [ -f "$PID_FILE" ]; then
        pid="$(cat "$PID_FILE")"
    fi
    pid_entries=("$SERVICE_LABEL:$pid")

    # Linux: stop and disable systemd service
    log_info "Stopping and disabling systemd service..."
    sudo systemctl stop "$SERVICE_LABEL"
    sudo systemctl disable "$SERVICE_LABEL"

    if ! wait_for_daemon_death "$STOP_WAIT_SECONDS" "${pid_entries[@]}"; then
        kill_managed_pid "$SERVICE_LABEL" "$pid"
        wait_for_daemon_death "$STOP_KILL_WAIT_SECONDS" "${pid_entries[@]}"
    fi

    # Clean up PID file
    if [ -f "$PID_FILE" ]; then
        rm -f "$PID_FILE"
    fi

    log_info "Daemon stopped and verified (service unloaded)"
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
        check_managed_launchd_units_complete || overall_ok=1
        status_launchd_unit "$DOCS_WATCH_LABEL" || overall_ok=1
        # cron is a periodic StartInterval unit: loaded but idle between runs.
        status_launchd_periodic_unit "$CRON_LABEL" || overall_ok=1
    fi

    # Check service manager status
    if [ "$PLATFORM" != "macos" ]; then
        SERVICE_STATUS=$(systemctl is-active "$SERVICE_LABEL" 2>/dev/null || echo "inactive")
        log_info "systemctl status: $SERVICE_STATUS"
        if [ "$SERVICE_STATUS" != "active" ]; then
            log_error "Service is not active: $SERVICE_STATUS"
            return 1
        fi
        CRON_TIMER_STATUS=$(systemctl is-active teleclaude-cron.timer 2>/dev/null || echo "inactive")
        log_info "cron timer status: $CRON_TIMER_STATUS"
        if [ "$CRON_TIMER_STATUS" != "active" ]; then
            log_error "cron timer is not active: $CRON_TIMER_STATUS"
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
        # restart reaches no install path on its own; heal a missing managed
        # plist (e.g. cron) so `make restart` reinstalls it, matching start.
        ensure_launchd_managed_plists
        KICKSTART_OUT=$(launchctl kickstart -k "$domain/$SERVICE_LABEL" 2>&1) || {
            log_error "launchctl kickstart failed: $KICKSTART_OUT"
            return 1
        }
        restart_launchd_unit "$DOCS_WATCH_LABEL"
        # Load-only: keep the periodic unit loaded without forcing an
        # off-schedule run (do not kickstart it).
        start_launchd_unit "$CRON_LABEL"

        # PID may remain unchanged on some macOS restarts; verify via health instead.
        NEW_PID=$(launchctl print "$domain/$SERVICE_LABEL" 2>/dev/null | awk -F' = ' '/^[[:space:]]*pid[[:space:]]*=/{print $2; exit}' || true)
        if [ -n "$OLD_PID" ] && [ -n "$NEW_PID" ] && [ "$NEW_PID" = "$OLD_PID" ]; then
            log_warn "launchctl kickstart pid unchanged ($NEW_PID); verifying health"
        fi
    else
        # Linux has no managed-set self-heal; install/heal the cron timer
        # idempotently before restart so a missing timer is restored.
        install_systemd_cron_service
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
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
