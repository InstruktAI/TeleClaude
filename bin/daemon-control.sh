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
# Host services may only be controlled from a main or release checkout — a
# worktree-rooted service would pin host lifecycle to an ephemeral branch checkout. Linked worktrees live at <main>/trees/<name>:
# refuse, loudly, however PROJECT_ROOT was resolved (derived or explicit).
if [ "$(basename "$(dirname "$PROJECT_ROOT")")" = "trees" ]; then
    echo "[FATAL] daemon-control.sh invoked from a worktree ($PROJECT_ROOT). Controlling host services from a worktree is not allowed." >&2
    exit 1
fi

# Service definitions (labels, launchd resolvers, deploy primitive) live in
# install_services.sh, shared with bin/install.sh so the two cannot drift.
# shellcheck source=/dev/null
source "$SCRIPT_DIR/init/install_services.sh"
CRON_TIMER_UNIT="${CRON_LABEL}.timer"
CRON_SERVICE_UNIT="${CRON_LABEL}.service"
_SYSTEMD_ACTIVE_STATE="active"
_SYSTEMD_INACTIVE_STATE="inactive"
_SYSTEMD_FAILED_STATE="failed"
_SYSTEMD_UNKNOWN_STATE="unknown"

# Configuration
# The process record lives in the installation root, outside every release, so a release switch keeps it.
PID_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/instrukt-ai/teleclaude/teleclaude.pid"
LOG_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/instrukt-ai/teleclaude/teleclaude.log"
API_SOCKET="/tmp/teleclaude-api.sock"
# Startup soft warning threshold in seconds. Startup keeps waiting past this
# threshold and emits warnings instead of failing hard.
STARTUP_WAIT_SECONDS="${TELECLAUDE_DAEMON_STARTUP_WAIT_S:-15}"
# Bounded window for the configured Redis to connect at least once. A reachable
# Redis connects sub-second; exceeding this window means REDIS_CLUSTER_URL is misconfigured
# or the server is unreachable, and `make start` reports failure.
REDIS_READY_WAIT_SECONDS="${TELECLAUDE_DAEMON_REDIS_READY_WAIT_S:-15}"
STOP_WAIT_SECONDS="${TELECLAUDE_DAEMON_STOP_WAIT_S:-25}"
STOP_KILL_WAIT_SECONDS="${TELECLAUDE_DAEMON_STOP_KILL_WAIT_S:-5}"
STARTUP_STREAM_PID=""
# Host-side preparation of the running daemon before an ordinary stop or restart
# (teleclaude.runtime.daemon_shutdown_control owns the observation, signalling and typed outcomes).
DAEMON_CONTROL_PYTHON="$PROJECT_ROOT/.venv/bin/python"
PREPARE_UNSUPPORTED_EXIT=10
PREPARE_DEFERRED_EXIT=15
ADMISSION_CLOSED_EXIT=16
# prepare_daemon_for_shutdown return code for a window that expired on a daemon that completes its
# own shutdown once its accepted work settles (0 prepared, 1 withheld, 2 not running).
PREPARE_DEFERRED_RETURN=3
# Set to 1 (make restart LEGACY_ACTIVATION=1) to activate the preparation protocol on a
# daemon that predates it. It reports observed quiescence only, never atomic draining.
LEGACY_ACTIVATION="${LEGACY_ACTIVATION:-0}"
STOP_OUTCOME_FILE="${STOP_OUTCOME_FILE:-}"
PREPARED_PID=""
DEFERRED_PID=""
STOP_OUTCOME_STOPPED="stopped"
STOP_OUTCOME_CLEANUP_FAILURE="stopped_cleanup_failure"
STOP_OUTCOME_WITHHELD_DRAINING="withheld_draining"
STOP_OUTCOME_WITHHELD="withheld"

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

record_stop_outcome() {
    if [ -n "$STOP_OUTCOME_FILE" ]; then
        printf '%s\n' "$1" > "$STOP_OUTCOME_FILE"
    fi
}

unit_name() {
    case "$1" in
        "$V1_DAEMON_LABEL")
            printf 'v1 daemon'
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
    local env_path="${TELECLAUDE_HOME:-$HOME/.teleclaude}/.env"
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

# The daemon cannot boot on a machine configuration that does not load; refuse before touching it.
require_loadable_machine_config() {
    PYTHONPATH="$PROJECT_ROOT" "$DAEMON_CONTROL_PYTHON" -m teleclaude.entrypoints.machine_config_check
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

is_outliving_launchd_label() {
    local candidate="$1"
    local label
    while IFS= read -r label; do
        if [ "$candidate" = "$label" ]; then
            return 0
        fi
    done < <(outliving_launchd_labels)
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
        if ! is_managed_launchd_label "$label" && ! is_outliving_launchd_label "$label"; then
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
    require_loadable_machine_config || return 1

    log_info "Starting TeleClaude daemon via $PLATFORM service manager..."

    if [ "$PLATFORM" = "macos" ]; then
        ensure_launchd_managed_plists
        check_managed_launchd_units_complete || return 1
    else
        # Content-gated: a no-op once every definition already matches.
        install_service
    fi

    # The receiver's units are deployed or withdrawn while the daemon is stopped, so the port is settled for
    # whichever of the two serves the ingress; a failure fails the start before the daemon runs.
    if ! install_ingress_receiver; then
        log_error "Failed to deploy or withdraw the ingress receiver"
        return 1
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
            log_error "Redis is a hard dependency. Verify REDIS_CLUSTER_URL points to a reachable server, then re-run 'make start' (see 'telec config wizard')"
            return 1
        fi
        if [ "$PLATFORM" != "macos" ]; then
            if ! _tc_sudo "enable and start the periodic job timer" systemctl enable --now "$CRON_TIMER_UNIT"; then
                stop_startup_log_stream
                log_error "Failed to activate the periodic job timer: $CRON_TIMER_UNIT"
                return 1
            fi
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

# The pid the service manager runs for the daemon; empty when none is running.
manager_daemon_pid() {
    local pid
    if [ "$PLATFORM" = "macos" ]; then
        launchd_unit_pid "$SERVICE_LABEL"
        return 0
    fi
    pid="$(systemd_main_pid)"
    if [ -z "$pid" ] && [ -f "$PID_FILE" ]; then
        pid="$(cat "$PID_FILE")"
    fi
    printf '%s\n' "$pid"
}

run_shutdown_control() {
    local verb="$1"
    local pid="$2"
    PYTHONPATH="$PROJECT_ROOT" "$DAEMON_CONTROL_PYTHON" -m teleclaude.runtime.daemon_shutdown_control \
        "$verb" --socket "$API_SOCKET" --manager-pid "$pid" --pid-file "$PID_FILE"
}

# Report the running daemon's admission state for `make status`. Returns 0 while admission
# is open (or the daemon predates the observation); returns 1, having said why, when
# admission is closed or the observation cannot be read.
report_admission_state() {
    local output
    local rc=0
    if [ ! -x "$DAEMON_CONTROL_PYTHON" ]; then
        log_warn "Admission state: UNKNOWN ($DAEMON_CONTROL_PYTHON is missing; run 'make install')"
        return 1
    fi
    output="$(PYTHONPATH="$PROJECT_ROOT" "$DAEMON_CONTROL_PYTHON" -m teleclaude.runtime.daemon_shutdown_control \
        status --socket "$API_SOCKET" 2>&1)" || rc=$?
    case "$rc" in
        0)
            log_info "Admission: OK ($output)"
            ;;
        "$ADMISSION_CLOSED_EXIT")
            log_warn "Admission: CLOSED, the daemon is draining ($output)"
            return 1
            ;;
        "$PREPARE_UNSUPPORTED_EXIT")
            log_info "Admission: not reported (the running daemon predates the preparation protocol)"
            ;;
        *)
            log_warn "Admission: UNREADABLE ($output)"
            return 1
            ;;
    esac
}

# Prepare the running daemon before any service-manager action.
# Returns 0 and sets PREPARED_PID when that exact instance reported drained (or, with
# LEGACY_ACTIVATION=1, when a positively identified legacy runtime is observed quiescent);
# returns 2 when no daemon is running; returns PREPARE_DEFERRED_RETURN and sets DEFERRED_PID
# when the window expired on a daemon that completes its own shutdown once its accepted work
# settles; returns 1, having reported why, when the service-manager action must be withheld.
# Nothing is ever forcibly terminated here.
prepare_daemon_for_shutdown() {
    local pid
    local output
    local rc=0
    PREPARED_PID=""
    DEFERRED_PID=""

    pid="$(manager_daemon_pid)"
    if [ -z "$pid" ] || ! is_pid_alive "$pid"; then
        return 2
    fi
    if [ ! -x "$DAEMON_CONTROL_PYTHON" ]; then
        log_error "Cannot prepare the daemon: $DAEMON_CONTROL_PYTHON is missing (run 'make install')"
        return 1
    fi

    log_info "Preparing daemon (pid $pid): closing admission and settling accepted work..."
    output="$(run_shutdown_control prepare "$pid")" || rc=$?
    if [ "$rc" -eq 0 ]; then
        PREPARED_PID="$output"
        log_info "Daemon instance $PREPARED_PID is drained"
        return 0
    fi

    if [ "$rc" -eq "$PREPARE_DEFERRED_EXIT" ]; then
        DEFERRED_PID="$pid"
        return "$PREPARE_DEFERRED_RETURN"
    fi

    if [ "$rc" -ne "$PREPARE_UNSUPPORTED_EXIT" ]; then
        log_error "Preparation incomplete; the service manager was not asked to act and nothing was terminated"
        return 1
    fi

    if [ "$LEGACY_ACTIVATION" != "1" ]; then
        log_error "The running daemon predates the preparation protocol. Its first activation is explicit: make restart LEGACY_ACTIVATION=1"
        log_error "That path observes quiescence only: it neither closes admission nor proves effects have settled"
        return 1
    fi

    rc=0
    output="$(run_shutdown_control legacy "$pid")" || rc=$?
    if [ "$rc" -ne 0 ]; then
        log_error "Legacy activation refused; the service manager was not asked to act and nothing was terminated"
        return 1
    fi
    PREPARED_PID="$output"
    log_warn "Legacy activation: durable work was observed quiescent; admission was not closed and effects are not proven settled"
    return 0
}

# Send SIGTERM to a prepared daemon. A delivery failure is reported with its reason; the
# caller's wait for the process to exit still decides the outcome, because a process that
# exited between preparation and this signal is already where the restart wants it.
signal_prepared_daemon() {
    local pid="$1"
    local kill_error
    if ! kill_error="$(kill -TERM "$pid" 2>&1)"; then
        log_warn "SIGTERM to prepared daemon (pid $pid) was not delivered: $kill_error"
    fi
}

systemd_unit_active() {
    local unit="$1"
    local state=""
    local exit_code=0
    state="$(systemctl is-active "$unit" 2>/dev/null)" || exit_code=$?
    if [ "$exit_code" -eq 0 ] && [ "$state" = "$_SYSTEMD_ACTIVE_STATE" ]; then
        return 0
    fi
    case "$state" in
        "$_SYSTEMD_INACTIVE_STATE"|"$_SYSTEMD_FAILED_STATE"|"$_SYSTEMD_UNKNOWN_STATE")
            return 1
            ;;
        *)
            log_error "Could not establish the active state of systemd unit $unit"
            return 2
            ;;
    esac
}

stop_systemd_periodic_units() {
    local timer_state=0
    local service_state=0
    local cleanup_failed=0
    systemd_unit_active "$CRON_TIMER_UNIT" || timer_state=$?
    systemd_unit_active "$CRON_SERVICE_UNIT" || service_state=$?
    if [ "$timer_state" -gt 1 ] || [ "$service_state" -gt 1 ]; then
        cleanup_failed=1
    fi

    if [ "$timer_state" -ne 1 ]; then
        if ! _tc_sudo "stop the periodic job timer" systemctl stop "$CRON_TIMER_UNIT"; then
            cleanup_failed=1
        fi
    fi

    if [ "$service_state" -ne 1 ]; then
        if ! _tc_sudo "stop the periodic job service" systemctl stop "$CRON_SERVICE_UNIT"; then
            cleanup_failed=1
        fi
    fi

    if systemctl is-enabled --quiet "$CRON_TIMER_UNIT"; then
        if ! _tc_sudo "disable the periodic job timer" systemctl disable "$CRON_TIMER_UNIT"; then
            cleanup_failed=1
        fi
    fi

    timer_state=0
    service_state=0
    systemd_unit_active "$CRON_TIMER_UNIT" || timer_state=$?
    systemd_unit_active "$CRON_SERVICE_UNIT" || service_state=$?
    if [ "$timer_state" -ne 1 ] || [ "$service_state" -ne 1 ]; then
        log_error "Periodic job units remain active after stop"
        cleanup_failed=1
    fi
    if [ "$cleanup_failed" -ne 0 ]; then
        return 1
    fi
    return 0
}

# Stop daemon via service manager
stop_daemon() {
    log_info "Stopping TeleClaude daemon..."
    local pid_entries=()
    local label
    local pid
    local entry
    local prepare_rc=0
    local periodic_cleanup_failed=0

    prepare_daemon_for_shutdown || prepare_rc=$?
    if [ "$prepare_rc" -eq "$PREPARE_DEFERRED_RETURN" ]; then
        log_error "Stop withheld: the daemon (pid $DEFERRED_PID) was left running and draining"
        log_error "It completes its own shutdown once its accepted work settles and the service manager relaunches it; keeping it down then takes another 'make stop'"
        record_stop_outcome "$STOP_OUTCOME_WITHHELD_DRAINING"
        return 1
    fi
    if [ "$prepare_rc" -eq 1 ]; then
        log_error "Stop withheld: the daemon was left running"
        record_stop_outcome "$STOP_OUTCOME_WITHHELD"
        return 1
    fi

    if [ "$PLATFORM" != "macos" ] && ! stop_systemd_periodic_units; then
        log_error "Periodic job unit cleanup failed; continuing daemon shutdown"
        periodic_cleanup_failed=1
    fi

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
            if ! wait_for_daemon_death "$STOP_KILL_WAIT_SECONDS" "${pid_entries[@]}"; then
                record_stop_outcome "$STOP_OUTCOME_WITHHELD"
                return 1
            fi
        fi

        while IFS= read -r label; do
            if is_launchd_unit_loaded "$label"; then
                log_error "$(unit_name "$label"): still loaded after stop"
                record_stop_outcome "$STOP_OUTCOME_WITHHELD"
                return 1
            fi
        done < <(managed_launchd_labels)

        if [ -f "$PID_FILE" ]; then
            rm -f "$PID_FILE"
        fi
        log_info "Managed launchd units stopped and verified"
        record_stop_outcome "$STOP_OUTCOME_STOPPED"
        return 0
    fi

    pid="$(systemd_main_pid)"
    if [ -z "$pid" ] && [ -f "$PID_FILE" ]; then
        pid="$(cat "$PID_FILE")"
    fi
    pid_entries=("$SERVICE_LABEL:$pid")

    # Linux: stop and disable systemd service
    log_info "Stopping and disabling systemd service..."
    local stop_command_failed=0
    local disable_command_failed=0
    local final_pid
    local service_status
    if ! sudo systemctl stop "$SERVICE_LABEL"; then
        stop_command_failed=1
        log_error "The service manager refused to stop $SERVICE_LABEL"
    fi
    if ! sudo systemctl disable "$SERVICE_LABEL"; then
        disable_command_failed=1
        log_error "The service manager refused to disable $SERVICE_LABEL"
    fi

    if ! wait_for_daemon_death "$STOP_WAIT_SECONDS" "${pid_entries[@]}"; then
        kill_managed_pid "$SERVICE_LABEL" "$pid"
        if ! wait_for_daemon_death "$STOP_KILL_WAIT_SECONDS" "${pid_entries[@]}"; then
            record_stop_outcome "$STOP_OUTCOME_WITHHELD"
            return 1
        fi
    fi

    final_pid="$(systemd_main_pid)"
    service_status="$(systemctl is-active "$SERVICE_LABEL" 2>/dev/null || true)"
    if [ -n "$final_pid" ] || { [ "$service_status" != "inactive" ] && [ "$service_status" != "failed" ]; }; then
        log_error "The systemd service remains active after stop"
        record_stop_outcome "$STOP_OUTCOME_WITHHELD"
        return 1
    fi
    if [ "$stop_command_failed" -ne 0 ] || [ "$disable_command_failed" -ne 0 ]; then
        record_stop_outcome "$STOP_OUTCOME_WITHHELD"
        return 1
    fi

    # Clean up PID file
    if [ -f "$PID_FILE" ]; then
        rm -f "$PID_FILE"
    fi

    log_info "Daemon stopped and verified (service unloaded)"
    if [ "$periodic_cleanup_failed" -ne 0 ]; then
        record_stop_outcome "$STOP_OUTCOME_CLEANUP_FAILURE"
        return 1
    fi
    record_stop_outcome "$STOP_OUTCOME_STOPPED"
    return 0
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
        CRON_TIMER_STATUS=$(systemctl is-active "$CRON_TIMER_UNIT" 2>/dev/null || echo "inactive")
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
                report_admission_state || overall_ok=1
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

    "$DAEMON_CONTROL_PYTHON" -m teleclaude.core.integration.daemon_window || true

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
    if ! require_loadable_machine_config; then
        log_error "Restart withheld: the daemon was left running"
        return 1
    fi

    local prepare_rc=0
    prepare_daemon_for_shutdown || prepare_rc=$?
    if [ "$prepare_rc" -eq "$PREPARE_DEFERRED_RETURN" ]; then
        # No heal step and no service-manager action: those can replace a draining daemon, and the
        # daemon completes the restart itself once its accepted work settles.
        log_warn "Preparation did not complete; the restart is deferred to the draining daemon (pid $DEFERRED_PID)"
        log_warn "It exits once its accepted work settles and the service manager starts it on the installed code"
        return 0
    fi
    if [ "$prepare_rc" -eq 1 ]; then
        log_error "Restart withheld: the daemon was left running"
        return 1
    fi

    if [ "$prepare_rc" -eq 0 ]; then
        log_info "Terminating prepared daemon (pid $PREPARED_PID)..."
        signal_prepared_daemon "$PREPARED_PID"
        if ! wait_for_daemon_death "$STOP_WAIT_SECONDS" "$SERVICE_LABEL:$PREPARED_PID"; then
            log_error "Prepared daemon did not exit within ${STOP_WAIT_SECONDS}s; not forcing it ('make kill' is the explicit forced path)"
            return 1
        fi
    fi

    # Nothing may follow the service-manager action; see daemon-availability.
    if [ "$PLATFORM" = "macos" ]; then
        local domain
        domain="$(launchd_domain)"
        # restart reaches no install path on its own; heal a missing managed
        # plist (e.g. cron) so `make restart` reinstalls it, matching start.
        ensure_launchd_managed_plists
        # Load-only: keep the periodic unit loaded without forcing an
        # off-schedule run (do not kickstart it).
        start_launchd_unit "$CRON_LABEL"
        if ! is_service_loaded; then
            start_launchd_unit "$SERVICE_LABEL"
            return $?
        fi
        # Not forceful: the prepared instance has exited, so this adopts the KeepAlive
        # relaunch or starts the unit; a daemon that is already running is left alone.
        exec launchctl kickstart "$domain/$SERVICE_LABEL"
    else
        # Linux has no managed-set self-heal; install/heal the cron timer
        # idempotently before restart so a missing timer is restored.
        install_systemd_cron_service
        exec sudo systemctl restart "$SERVICE_LABEL"
    fi
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
