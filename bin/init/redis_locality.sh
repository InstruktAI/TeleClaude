#!/usr/bin/env bash
# REDIS_URL locality classification, shared by install.sh and its tests.
#
# redis_url_host  <url-value>     -> prints the lowercased host (scheme, credentials,
#                                    port, path, and IPv6 brackets stripped). Empty when
#                                    the URL carries no host (e.g. "redis://" or "").
# redis_host_is_loopback <host>   -> exit 0 when host is localhost, IPv6 ::1, or a
#                                    numeric 127.0.0.0/8 address; exit 1 otherwise.
#
# The skip-local-Redis decision belongs to the caller: skip only when the parsed
# host is non-empty AND not loopback (a genuinely remote endpoint). A host-less URL
# is neither remote nor loopback, so it must fall through to the local prompt.

redis_url_host() {
    local value="$1"
    value="${value%\"}" && value="${value#\"}"
    value="${value%\'}" && value="${value#\'}"
    local hostport="${value#*://}" # drop scheme://
    hostport="${hostport##*@}"     # drop user:pass@ credentials
    hostport="${hostport%%/*}"     # drop /path
    local host
    if [ "${hostport#\[}" != "$hostport" ]; then
        host="${hostport#\[}"      # bracketed IPv6: strip leading [
        host="${host%%\]*}"        # and trailing ]...
    else
        host="${hostport%%:*}"     # drop :port
    fi
    printf '%s' "$host" | tr '[:upper:]' '[:lower:]'
}

redis_host_is_loopback() {
    local host="$1"
    case "$host" in
        localhost | ::1) return 0 ;;
    esac
    # Numeric IPv4 loopback only (127.0.0.0/8) — not arbitrary "127.*" hostnames.
    [[ "$host" =~ ^127\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]] && return 0
    return 1
}
