#!/usr/bin/env bash
# REDIS_URL locality classification, shared by install.sh and its tests.
#
# redis_url_host  <url-value>  -> prints the lowercased host (scheme, credentials,
#                                 port, path, and IPv6 brackets stripped).
# redis_url_is_local <url-value> -> exit 0 when the host is a loopback endpoint
#                                 (localhost any-case, IPv6 ::1, or 127.0.0.0/8),
#                                 exit 1 for a remote host or an empty/host-less URL.

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

redis_url_is_local() {
    local host
    host="$(redis_url_host "$1")"
    [ -z "$host" ] && return 1
    case "$host" in
        localhost | ::1 | 127.*) return 0 ;;
        *) return 1 ;;
    esac
}
