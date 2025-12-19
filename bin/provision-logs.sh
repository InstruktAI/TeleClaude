#!/usr/bin/env bash
#
# Provision the canonical InstruktAI log directory and file for a service.
#
# Default:
#   /var/log/instrukt-ai/<app>/<app>.log
#
# Optional override (escape hatch):
#   INSTRUKT_AI_LOG_ROOT=/some/dir  -> /some/dir/<app>/<app>.log
#
# This script is intentionally "no fallback": it either provisions the canonical
# log path or fails with a clear error.

set -euo pipefail

usage() {
    echo "Usage: $0 <app> [--print-log-file]"
    echo ""
    echo "Examples:"
    echo "  $0 teleclaude"
    echo "  $0 teleclaude --print-log-file"
}

if [[ "${1:-}" == "" ]] || [[ "${1:-}" == "-h" ]] || [[ "${1:-}" == "--help" ]]; then
    usage
    exit 1
fi

APP_RAW="$1"
shift

PRINT_LOG_FILE=false
NON_INTERACTIVE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes|--non-interactive)
            NON_INTERACTIVE=true
            shift
            ;;
        --print-log-file)
            PRINT_LOG_FILE=true
            shift
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

DEFAULT_ROOT="/var/log/instrukt-ai"

normalize_fs_app_name() {
    echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/-+/-/g; s/^-+//; s/-+$//'
}

read_env_var_from_file() {
    local file="$1"
    local key="$2"
    # Naive dotenv parsing: KEY=value (no quotes handling, consistent with our generated .env).
    if [[ -f "$file" ]]; then
        awk -F= -v k="$key" '$1 == k {sub(/^[^=]*=/, "", $0); print $0; exit}' "$file"
    fi
}

FS_APP_NAME="$(normalize_fs_app_name "$APP_RAW")"
if [[ -z "$FS_APP_NAME" ]]; then
    echo "Invalid app name: $APP_RAW" >&2
    exit 1
fi

log_root="${INSTRUKT_AI_LOG_ROOT:-}"
if [[ -z "$log_root" ]]; then
    log_root="$(read_env_var_from_file "$ENV_FILE" "INSTRUKT_AI_LOG_ROOT")"
fi

default_log_dir="$DEFAULT_ROOT/$FS_APP_NAME"
default_log_file="$default_log_dir/$FS_APP_NAME.log"

if [[ -z "$log_root" ]]; then
    # Only prompt on first provision (interactive shell, no existing default log file).
    if [[ "$NON_INTERACTIVE" == false && -t 0 && -t 1 && ! -f "$default_log_file" ]]; then
        echo "Log root (preferred: $DEFAULT_ROOT)"
        read -r -p "Log root directory [$DEFAULT_ROOT]: " input_root
        log_root="${input_root:-$DEFAULT_ROOT}"
    else
        log_root="$DEFAULT_ROOT"
    fi
fi

log_root="${log_root%/}"
log_dir="$log_root/$FS_APP_NAME"
log_file="$log_dir/$FS_APP_NAME.log"

provision_without_sudo() {
    mkdir -p "$log_dir"
    touch "$log_file"
    chmod 755 "$log_dir" || true
    chmod 644 "$log_file" || true
}

provision_with_sudo() {
    sudo mkdir -p "$log_dir"
    sudo touch "$log_file"
    sudo chown "$USER:$(id -gn)" "$log_dir" "$log_file"
    sudo chmod 755 "$log_dir"
    sudo chmod 644 "$log_file"
}

if provision_without_sudo 2>/dev/null; then
    :
else
    provision_with_sudo
fi

# Persist override for daemon startup if we chose a non-default root and .env exists.
if [[ "$log_root" != "$DEFAULT_ROOT" ]]; then
    if [[ -f "$ENV_FILE" ]]; then
        if grep -q "^INSTRUKT_AI_LOG_ROOT=" "$ENV_FILE"; then
            tmp="$(mktemp)"
            awk -v v="$log_root" 'BEGIN{done=0} {if ($0 ~ /^INSTRUKT_AI_LOG_ROOT=/) {print "INSTRUKT_AI_LOG_ROOT=" v; done=1} else {print $0}} END{if (!done) print "INSTRUKT_AI_LOG_ROOT=" v}' "$ENV_FILE" > "$tmp"
            mv "$tmp" "$ENV_FILE"
        else
            echo "" >> "$ENV_FILE"
            echo "INSTRUKT_AI_LOG_ROOT=$log_root" >> "$ENV_FILE"
        fi
    else
        echo "Note: INSTRUKT_AI_LOG_ROOT=$log_root (add this to $ENV_FILE for the daemon)" >&2
    fi
fi

if [[ "$PRINT_LOG_FILE" == true ]]; then
    echo "$log_file"
fi
