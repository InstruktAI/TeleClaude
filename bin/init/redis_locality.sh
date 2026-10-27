#!/usr/bin/env bash
# Cluster Redis URL locality classification, shared by install.sh and its tests.
#
# redis_url_host <url-value>            -> prints the lowercased host (scheme,
#                                         credentials, port, path, and IPv6 brackets
#                                         stripped). Empty when the URL carries no host.
# redis_host_is_loopback <host>         -> exit 0 when host is localhost, IPv6 ::1, or a
#                                         valid numeric 127.0.0.0/8 address.
# redis_url_skips_local_install <url>   -> exit 0 when the URL names a usable remote
#                                         endpoint, so the local Redis install/prompt can
#                                         be skipped. A loopback or host-less URL returns 1.

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
    # Numeric IPv4 loopback only: 127.x.x.x with every octet a valid 0..255.
    local octet='(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])'
    [[ "$host" =~ ^127\.${octet}\.${octet}\.${octet}$ ]] && return 0
    return 1
}

redis_url_skips_local_install() {
    local host
    host="$(redis_url_host "$1")"
    [ -n "$host" ] && ! redis_host_is_loopback "$host"
}

# machine_cluster_redis_url <env file>    -> prints the cluster Redis URL the machine environment names:
#                                            REDIS_CLUSTER_URL, else the earlier REDIS_URL; nothing when unset.
machine_cluster_redis_url() {
    local env_file="$1" name line
    [ -f "$env_file" ] || return 0
    for name in REDIS_CLUSTER_URL REDIS_URL; do
        line="$(grep -E "^${name}=.+" "$env_file" | head -1)"
        if [ -n "$line" ]; then
            printf '%s\n' "${line#"${name}"=}"
            return 0
        fi
    done
}
