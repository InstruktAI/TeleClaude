#!/bin/bash
set -euo pipefail
out="${TELECLAUDE_API_WATCH_LOG:-/tmp/teleclaude-unlink-attrib.log}"
mkdir -p "$(dirname "$out")"
: > "$out"
# Watch filesystem events and attribute unlink events to a PID/command.
while true; do
  set +e
  /usr/bin/sudo -n /usr/bin/fs_usage -w -f filesystem 2>/dev/null | while IFS= read -r line; do
    case "$line" in
      *"unlink"*"teleclaude-api.sock"*)
        proc=$(echo "$line" | awk '{print $NF}')
        pid=${proc##*.}
        echo "UNLINK_EVENT: $line" >> "$out"
        if [[ "$pid" =~ ^[0-9]+$ ]]; then
          /bin/ps -p "$pid" -o pid,ppid,command >> "$out" 2>&1 || echo "ps_failed pid=$pid" >> "$out"
        else
          echo "pid_parse_failed proc=$proc" >> "$out"
        fi
        echo "---" >> "$out"
        ;;
      *"bind"*"teleclaude-api.sock"*)
        echo "BIND_EVENT: $line" >> "$out"
        ;;
    esac
  done
  set -e
  sleep 2
done
