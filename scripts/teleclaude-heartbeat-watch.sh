#!/usr/bin/env bash
set -euo pipefail

REPO="${TELECLAUDE_HEARTBEAT_REPO:-/Users/Morriz/Workspace/InstruktAI/TeleClaude}"
LOG_FILE="${TELECLAUDE_HEARTBEAT_LOG:-/Users/Morriz/teleclaude-heartbeat.log}"
INTERVAL_SECONDS="${TELECLAUDE_HEARTBEAT_INTERVAL_SECONDS:-60}"
LOG_SINCE="${TELECLAUDE_HEARTBEAT_LOG_SINCE:-1m}"
ALERT_PATTERNS="${TELECLAUDE_HEARTBEAT_PATTERNS:-Received SIGTERM|Received SIGINT|Received SIGHUP|Wrapper request failed|Connection refused|MCP socket NOT responding|MCP socket health check failed|API connect failed|CRASH|killed|Wrapper request failed}"

log_path="$(dirname "$LOG_FILE")"
mkdir -p "$log_path"

run_status() {
  local ts="$1"
  local status_rc=0
  local status_output

  set +e
  status_output="$(cd "$REPO" && make status 2>&1)"
  status_rc=$?
  set -e

  if [[ "$status_rc" -eq 0 ]]; then
    echo "[${ts}] [teleclaude-heartbeat] status=healthy" >> "$LOG_FILE"
  else
    {
      echo "[${ts}] [teleclaude-heartbeat] status=failed exit=$status_rc"
      echo "$status_output"
      echo "[teleclaude-heartbeat] ---"
    } >> "$LOG_FILE"
  fi
}

run_events() {
  local ts="$1"
  local events_rc=0
  local events_output

  set +e
  events_output="$(instrukt-ai-logs teleclaude --since "$LOG_SINCE" --grep "$ALERT_PATTERNS" 2>&1)"
  events_rc=$?
  set -e

  if [[ -n "${events_output}" ]]; then
    {
      echo "[${ts}] [teleclaude-heartbeat] matched events in last ${LOG_SINCE} (instrukt-ai-logs rc=$events_rc)"
      echo "$events_output"
      echo "[teleclaude-heartbeat] ---"
    } >> "$LOG_FILE"
  fi
}

ts="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "[${ts}] [teleclaude-heartbeat] Starting watcher (interval=${INTERVAL_SECONDS}s)" >> "$LOG_FILE"

while true; do
  ts="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  run_status "$ts"
  run_events "$ts"
  sleep "$INTERVAL_SECONDS"
done
