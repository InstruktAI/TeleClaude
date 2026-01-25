#!/bin/bash
set -euo pipefail

out="${TELECLAUDE_API_WATCH_LOG:-/tmp/teleclaude-unlink-attrib.log}"
mkdir -p "$(dirname "$out")"

# Watch filesystem events from the TeleClaude daemon process only to avoid
# scanning the entire system (fs_usage is expensive otherwise).
while true; do
  daemon_pid="$(pgrep -f 'teleclaude.daemon' | head -n1 || true)"
  if [[ -z "${daemon_pid}" ]]; then
    sleep 1
    continue
  fi

  /usr/bin/sudo -n /usr/bin/fs_usage -w -f filesys -t 1 -p "${daemon_pid}" 2>/dev/null | while IFS= read -r line; do
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
  sleep 1
done
