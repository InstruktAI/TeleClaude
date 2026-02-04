#!/bin/bash
set -euo pipefail

log="${TELECLAUDE_SIGTERM_LOG:-/var/log/instrukt-ai/teleclaude/monitoring/sigterm-watch.log}"
mkdir -p "$(dirname "$log")"

echo "[${DATE_OVERRIDE:-$(date -u '+%Y-%m-%d %H:%M:%S')}] dtrace_start" >> "$log"
# Best-effort signal attribution. If dtrace is unavailable, fall back to launchctl state snapshots.
if /usr/bin/sudo -n /usr/sbin/dtrace -q -n 'syscall::kill:entry /arg1 == SIGTERM/ { printf("%Y pid=%d exec=%s target=%d\n", walltimestamp, pid, execname, arg0); }' >> "$log" 2>&1; then
  exit 0
fi

echo "[${DATE_OVERRIDE:-$(date -u '+%Y-%m-%d %H:%M:%S')}] dtrace_failed; switching to launchctl snapshots" >> "$log"
last_sig=""
while true; do
  snapshot="$(/bin/launchctl print gui/$(id -u)/ai.instrukt.teleclaude.daemon 2>/dev/null | /usr/bin/egrep -i 'state =|pid =|last exit|last terminating signal' || true)"
  if [[ -n "$snapshot" ]]; then
    if [[ "$snapshot" != "$last_sig" ]]; then
      echo "[${DATE_OVERRIDE:-$(date -u '+%Y-%m-%d %H:%M:%S')}] launchctl_snapshot" >> "$log"
      echo "$snapshot" >> "$log"
      echo "---" >> "$log"
      last_sig="$snapshot"
    fi
  fi
  sleep 10
done
