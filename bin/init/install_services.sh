#!/usr/bin/env bash
# TeleClaude service definition deployment
#
# Renders each launchd/systemd service definition from its template and
# deploys it only when the rendered content differs from what is already on
# disk. Sourced by bin/install.sh (every `make install`) and by
# bin/daemon-control.sh (self-heal on the lifecycle path); both give this
# file its own runtime context below, since neither caller defines the
# symbols the installer functions consume.
#
# This file sets no shell options at source time — `set -euo pipefail` here
# would persist into whichever caller sourced it. Option changes belong only
# in the standalone-execution footer at the bottom.

if ! declare -F log_info >/dev/null; then
    log_info() {
        printf '[INFO] %s\n' "$1"
    }
fi

if ! declare -F log_error >/dev/null; then
    log_error() {
        printf '[ERROR] %s\n' "$1" >&2
    }
fi

_tc_sudo() {
    local step="$1"
    shift
    if [ "${NON_INTERACTIVE:-false}" = true ] || [ ! -t 0 ]; then
        if sudo -n "$@"; then
            return 0
        fi
        log_error "$step needs sudo access that works without a prompt; run install from an authorized terminal or provide non-interactive sudo access."
        return 1
    fi
    if sudo "$@"; then
        return 0
    fi
    log_error "$step failed."
    return 1
}

# An on-demand run (`telec sync`) tells the commands it runs so through
# TELECLAUDE_MAINTENANCE_TRIGGER (teleclaude/core/integration/maintenance_trigger.py).
# On demand, installation deploys no service definition and reloads no running
# service; it names each difference instead. `--check` (direct execution) asks
# the same question without installing anything.
defer_service_changes() {
    [ "${TELECLAUDE_MAINTENANCE_TRIGGER:-}" = "on_demand" ] || [ "${TC_SERVICE_DEFINITION_CHECK:-false}" = true ]
}

# Project root: prefer a value the caller already resolved (PROJECT_ROOT),
# then bin/install.sh's INSTALL_DIR, then this file's own location.
if [ -n "${PROJECT_ROOT:-}" ]; then
    PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
elif [ -n "${INSTALL_DIR:-}" ]; then
    PROJECT_ROOT="$(cd "$INSTALL_DIR" && pwd)"
else
    PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

# The root every rendered definition names. A release of the installation is addressed through the
# installation's `current` pointer, never through its own folder; any other root names itself.
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/live_root.sh"
SERVICE_ROOT="$(live_root_of "$PROJECT_ROOT")"
SERVICE_DATA_HOME="$(installation_data_home)"

# Platform detection: do not clobber a value the sourcing caller already set.
if [ -z "${PLATFORM:-}" ]; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
        PLATFORM="macos"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        PLATFORM="linux"
    else
        log_error "Unsupported platform: $OSTYPE"
        exit 1
    fi
fi

# Service identity.
_DOCS_WATCH_SYSTEMD_SERVICE="teleclaude-docs-watch"
_DOCS_WATCH_SYSTEMD_UNIT="${_DOCS_WATCH_SYSTEMD_SERVICE}.service"
_DOCS_WATCH_SYSTEMD_PATH="/etc/systemd/system/${_DOCS_WATCH_SYSTEMD_UNIT}"
DOCS_WATCH_WITHDRAW_SETTLE_SECONDS=10
if [ "$PLATFORM" = "macos" ]; then
    V1_DAEMON_LABEL="ai.instrukt.teleclaude.daemon"
    DOCS_WATCH_LABEL="ai.instrukt.teleclaude.docs-watch"
    CRON_LABEL="ai.instrukt.teleclaude.cron"
    # TeleClaude's own local Redis, deployed by the install act (teleclaude/install/local_redis.py).
    LOCAL_REDIS_LABEL="ai.instrukt.teleclaude.redis"
    # The ingress computer's webhook receiver, which outlives the daemon (ADR-0148, ADR-0150).
    INGRESS_RECEIVER_LABEL="ai.instrukt.teleclaude.ingress-receiver"
    SERVICE_LABEL="$V1_DAEMON_LABEL"
    SERVICE_PATH="$HOME/Library/LaunchAgents/$SERVICE_LABEL.plist"
else
    SERVICE_LABEL="teleclaude"
    CRON_LABEL="teleclaude-cron"
    INGRESS_RECEIVER_LABEL="teleclaude-ingress-receiver"
    # bin/daemon-control.sh consumes SERVICE_PATH from this sourced module.
    # shellcheck disable=SC2034
    SERVICE_PATH="/etc/systemd/system/$SERVICE_LABEL.service"
fi

managed_launchd_labels() {
    printf '%s\n' "$V1_DAEMON_LABEL"
    printf '%s\n' "$CRON_LABEL"
}

# Units the installation deploys that outlive the daemon: stopping the daemon leaves them running.
outliving_launchd_labels() {
    printf '%s\n' "$LOCAL_REDIS_LABEL"
    printf '%s\n' "$INGRESS_RECEIVER_LABEL"
}

# launchd resolvers. These resolve and query; they perform no service
# operation, so they live with the definitions they render.
launchd_domain() {
    printf 'gui/%s\n' "$(id -u)"
}

launchd_path_env() {
    # Platform-published tool dirs first: ~/.local/bin (graphify, telec) and
    # ~/.cargo/bin (rust). The daemon shells out to these by bare name, so they
    # must be on its PATH for every project it manages.
    # See local/projects/teleclaude/spec/agent-shell-path (Implementation 2 — the daemon).
    local launchd_path="$HOME/.npm-global/bin:$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    printf '%s\n' "$launchd_path" | tr ':' '\n' | awk '!seen[$0]++' | tr '\n' ':' | sed 's/:$//'
}

launchd_plist_path() {
    local label="$1"
    printf '%s/Library/LaunchAgents/%s.plist\n' "$HOME" "$label"
}

is_launchd_unit_loaded() {
    local label="$1"
    launchctl print "$(launchd_domain)/$label" >/dev/null 2>&1
}

launchd_docs_watch_state() {
    local domain="$1"
    if ! launchctl print "$domain" >/dev/null 2>&1; then
        log_error "docs-watch: cannot query the launchd GUI domain $domain; restore manager access and rerun make install."
        return 1
    fi
    if launchctl print "$domain/$DOCS_WATCH_LABEL" >/dev/null 2>&1; then
        printf 'loaded\n'
    else
        printf 'not-loaded\n'
    fi
}

wait_for_launchd_docs_watch_unloaded() {
    local domain="$1"
    local timeout_seconds="$2"
    local deadline=$((SECONDS + timeout_seconds))
    local state

    while true; do
        if ! state="$(launchd_docs_watch_state "$domain")"; then
            return 1
        fi
        if [ "$state" = "not-loaded" ] || [ "$SECONDS" -ge "$deadline" ]; then
            printf '%s\n' "$state"
            return 0
        fi
        sleep 1
    done
}

systemd_docs_watch_state() {
    local load_state
    if ! load_state="$(_tc_sudo "query the docs-watch systemd unit" systemctl show --system --property=LoadState --value "$_DOCS_WATCH_SYSTEMD_UNIT" 2>&1)"; then
        log_error "docs-watch: cannot query $_DOCS_WATCH_SYSTEMD_UNIT in the system manager: $load_state; resolve the query failure and rerun make install."
        return 1
    fi
    case "$load_state" in
        loaded)
            printf 'loaded\n'
            ;;
        not-found)
            printf 'not-found\n'
            ;;
        *)
            log_error "docs-watch: unresolved system manager state for $_DOCS_WATCH_SYSTEMD_UNIT: $load_state; resolve the state and rerun make install."
            return 1
            ;;
    esac
}

docs_watch_definition_type_is_safe() {
    local definition_path="$1"
    local unit_name="$2"
    if [ -L "$definition_path" ] || { [ -e "$definition_path" ] && [ ! -f "$definition_path" ]; }; then
        log_error "docs-watch: unexpected definition type for $unit_name at $definition_path; move the conflicting object and rerun make install."
        return 1
    fi
}

# deploy_service_definition <rendered_file> <target_path> [--sudo]
#
# Compares rendered content against the deployed file and, only when they
# differ (or the target is absent), installs the rendered file at the
# target. Exit status is the caller's reload signal: 0 = the target changed,
# reload it; 1 = unchanged, do nothing; 2 = the write itself failed. Every
# caller goes through deploy_or_die below rather than calling this directly,
# so status 2 never has to be handled at each of the eight call sites.
# Platform-neutral — it takes the target path as a parameter and holds no
# launchd or systemd knowledge.
deploy_service_definition() {
    local rendered_file="$1"
    local target_path="$2"
    local use_sudo="${3:-}"

    # Host services may only be deployed from the main checkout — a
    # worktree-rooted deploy would bake trees/<slug> into a rendered
    # definition and point the fleet's real services at an ephemeral branch
    # checkout. Same test and reason as bin/daemon-control.sh's own refusal.
    if [ "$(basename "$(dirname "$PROJECT_ROOT")")" = "trees" ]; then
        log_error "install_services.sh invoked against a worktree ($PROJECT_ROOT). Deploying service definitions from a worktree is not allowed."
        exit 1
    fi

    if [ -f "$target_path" ] && cmp -s "$rendered_file" "$target_path"; then
        return 1
    fi

    # A deferred run names the difference and reports "unchanged", so no caller reloads.
    if defer_service_changes; then
        printf 'service definition differs from what installation would deploy: %s\n' "$target_path"
        return 1
    fi

    # Every call site below invokes this function (via deploy_or_die) as the
    # condition of an `if`/`!`, which suppresses `set -e` for the entire call
    # — a failed cp would otherwise fall through to the unconditional
    # `return 0` and be reported as a successful "changed" deploy while the
    # target keeps its stale content. Check the write explicitly instead.
    if [ "$use_sudo" = "--sudo" ]; then
        if ! _tc_sudo "deploy service definition to $target_path" cp "$rendered_file" "$target_path"; then
            return 2
        fi
    else
        if ! cp "$rendered_file" "$target_path"; then
            return 2
        fi
    fi
    return 0
}

# deploy_or_die <rendered_file> <target_path> [--sudo]
#
# Thin wrapper every installer calls instead of deploy_service_definition
# directly: a write failure (status 2) exits loudly rather than being
# swallowed by a caller's `if`/`if !` that only distinguishes true/false.
# Returns 0 (changed) or 1 (unchanged) — status 2 never reaches the caller.
# Does not touch rendered_file; callers still own removing their own temp
# files (one call site deploys a template directly, with nothing to remove).
deploy_or_die() {
    local rendered_file="$1"
    local target_path="$2"
    local use_sudo="${3:-}"
    local status=0

    deploy_service_definition "$rendered_file" "$target_path" "$use_sudo" || status=$?

    if [ "$status" -eq 2 ]; then
        log_error "Failed to deploy $target_path"
        exit 1
    fi
    return "$status"
}

# render_template_or_die <template_file> <rendered_file> [NAME=VALUE ...]
#
# A failed render exits explicitly because the callers run under conditionals
# that suppress `set -e`; the renderer has already reported the template error.
render_template_or_die() {
    local template_file="$1"
    local rendered_file="$2"
    shift 2

    if ! PYTHONPATH="$PROJECT_ROOT" "$PROJECT_ROOT/.venv/bin/python" -m teleclaude.entrypoints.render_template \
        "$template_file" "$rendered_file" "$@"; then
        rm -f "$rendered_file"
        exit 1
    fi
}

install_systemd_service() {
    local service_name="teleclaude"
    local service_file="/etc/systemd/system/${service_name}.service"
    local path_file="/etc/systemd/system/${service_name}-config.path"

    local rendered_service
    rendered_service="$(mktemp)"
    cat > "$rendered_service" <<EOF
[Unit]
Description=TeleClaude Terminal Bridge Daemon
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$SERVICE_ROOT
Environment="PATH=$SERVICE_ROOT/.venv/bin:$HOME/.npm-global/bin:$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin"
Environment="XDG_DATA_HOME=$SERVICE_DATA_HOME"
# SSH_AUTH_SOCK sourced from keychain in wrapper
ExecStart=$SERVICE_ROOT/bin/teleclaude-wrapper.sh
# Relaunch after clean exits too, as launchd KeepAlive does: the daemon applies
# restart-required config changes by shutting down gracefully. An explicit
# `systemctl stop` is never restarted.
Restart=always
RestartSec=10
LimitNOFILE=4096
StandardOutput=null
StandardError=null
KillMode=process

[Install]
WantedBy=multi-user.target
EOF

    # Watches config.yml and restarts the service on change; rendered and
    # gated independently of the service unit above since the two change for
    # unrelated reasons (config.yml location vs. wrapper/PATH).
    local rendered_path_unit
    rendered_path_unit="$(mktemp)"
    cat > "$rendered_path_unit" <<EOF
[Unit]
Description=TeleClaude Config File Watcher

[Path]
PathModified=$SERVICE_ROOT/config.yml
Unit=${service_name}.service

[Install]
WantedBy=multi-user.target
EOF

    local service_deployed=false
    local path_deployed=false

    if deploy_or_die "$rendered_service" "$service_file" --sudo; then
        service_deployed=true
    fi
    rm -f "$rendered_service"

    if deploy_or_die "$rendered_path_unit" "$path_file" --sudo; then
        path_deployed=true
    fi
    rm -f "$rendered_path_unit"

    if ! $service_deployed && ! $path_deployed; then
        return 0
    fi

    log_info "Deployed systemd daemon definition(s)"
    _tc_sudo "reload systemd after deploying the daemon service" systemctl daemon-reload

    if $service_deployed; then
        # A unit-state query needs no privilege, and a nonzero answer means inactive.
        if systemctl is-active --quiet "$service_name"; then
            _tc_sudo "restart $service_name" systemctl restart "$service_name"
        else
            _tc_sudo "enable $service_name" systemctl enable "$service_name"
        fi
    fi

    if $path_deployed; then
        if systemctl is-active --quiet "${service_name}-config.path"; then
            _tc_sudo "restart ${service_name}-config.path" systemctl restart "${service_name}-config.path"
        else
            _tc_sudo "enable ${service_name}-config.path" systemctl enable "${service_name}-config.path"
        fi
    fi
}

install_systemd_cron_service() {
    local service_name="$CRON_LABEL"
    local service_file="/etc/systemd/system/${service_name}.service"
    local timer_file="/etc/systemd/system/${service_name}.timer"
    local service_template="$PROJECT_ROOT/templates/teleclaude-cron.service"
    local timer_template="$PROJECT_ROOT/templates/teleclaude-cron.timer"
    # Run via the project venv interpreter (not `uv run`): the script's inline
    # PEP-723 metadata forces `uv run` into an isolated env without the project's
    # dependencies. Mirrors the launchd cron unit and the daemon service.
    local command="$SERVICE_ROOT/.venv/bin/python scripts/cron_runner.py"
    local service_path="$SERVICE_ROOT/.venv/bin:$HOME/.npm-global/bin:$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin"

    if [ ! -f "$service_template" ]; then
        log_error "Template file not found: $service_template"
        exit 1
    fi
    if [ ! -f "$timer_template" ]; then
        log_error "Template file not found: $timer_template"
        exit 1
    fi

    local rendered_service
    rendered_service="$(mktemp)"
    render_template_or_die "$service_template" "$rendered_service" \
        "COMMAND=$command" "WORKING_DIR=$SERVICE_ROOT" "PATH=$service_path" "XDG_DATA_HOME=$SERVICE_DATA_HOME"

    local service_deployed=false
    local timer_deployed=false

    if deploy_or_die "$rendered_service" "$service_file" --sudo; then
        service_deployed=true
    fi
    rm -f "$rendered_service"

    local rendered_timer
    rendered_timer="$(mktemp)"
    render_template_or_die "$timer_template" "$rendered_timer"

    if deploy_or_die "$rendered_timer" "$timer_file" --sudo; then
        timer_deployed=true
    fi
    rm -f "$rendered_timer"

    if ! $service_deployed && ! $timer_deployed; then
        return 0
    fi

    log_info "Deployed cron systemd service/timer"
    _tc_sudo "reload systemd after deploying the cron service" systemctl daemon-reload

    if systemctl is-active --quiet "${service_name}.timer"; then
        _tc_sudo "restart ${service_name}.timer" systemctl restart "${service_name}.timer"
    else
        _tc_sudo "enable ${service_name}.timer" systemctl enable "${service_name}.timer"
    fi
}

install_launchd_service() {
    local service_name="$V1_DAEMON_LABEL"
    local plist_file
    plist_file="$(launchd_plist_path "$service_name")"
    local template_file="$PROJECT_ROOT/templates/ai.instrukt.teleclaude.daemon.plist"

    mkdir -p "$HOME/Library/LaunchAgents"

    if [ ! -f "$template_file" ]; then
        log_error "Template file not found: $template_file"
        exit 1
    fi

    local launchd_path
    launchd_path="$(launchd_path_env)"

    local rendered_file
    rendered_file="$(mktemp)"
    render_template_or_die "$template_file" "$rendered_file" \
        "PYTHON_PATH=$SERVICE_ROOT/.venv/bin/python" "WORKING_DIR=$SERVICE_ROOT" "PATH=$launchd_path" "XDG_DATA_HOME=$SERVICE_DATA_HOME"

    if ! deploy_or_die "$rendered_file" "$plist_file"; then
        rm -f "$rendered_file"
        return 0
    fi
    rm -f "$rendered_file"

    log_info "Deployed launchd plist: $plist_file"

    local domain
    domain="$(launchd_domain)"
    if is_launchd_unit_loaded "$service_name"; then
        launchctl bootout "$domain" "$plist_file" 2>/dev/null || launchctl unload "$plist_file" 2>/dev/null || true
        if ! launchctl bootstrap "$domain" "$plist_file" 2>/dev/null; then
            launchctl load "$plist_file"
        fi
    else
        log_info "$service_name: not loaded; definition written for the next 'make start'"
    fi
}

install_launchd_cron_service() {
    local service_name="$CRON_LABEL"
    local plist_file
    plist_file="$(launchd_plist_path "$service_name")"
    local template_file="$PROJECT_ROOT/templates/ai.instrukt.teleclaude.cron.plist"

    mkdir -p "$HOME/Library/LaunchAgents"

    if [ ! -f "$template_file" ]; then
        log_error "Template file not found: $template_file"
        exit 1
    fi

    # The plist invokes the interpreter directly (no shell), so it runs the
    # project venv's Python — mirroring the daemon plist's {{PYTHON_PATH}}. The
    # script's inline PEP-723 metadata would otherwise force `uv run` into an
    # isolated env that lacks the project's dependencies.
    local launchd_path
    launchd_path="$(launchd_path_env)"

    local rendered_file
    rendered_file="$(mktemp)"
    render_template_or_die "$template_file" "$rendered_file" \
        "PYTHON_PATH=$SERVICE_ROOT/.venv/bin/python" "WORKING_DIR=$SERVICE_ROOT" "PATH=$launchd_path" "XDG_DATA_HOME=$SERVICE_DATA_HOME"

    if ! deploy_or_die "$rendered_file" "$plist_file"; then
        rm -f "$rendered_file"
        return 0
    fi
    rm -f "$rendered_file"

    log_info "Deployed cron plist: $plist_file"

    local domain
    domain="$(launchd_domain)"
    if is_launchd_unit_loaded "$service_name"; then
        launchctl bootout "$domain" "$plist_file" 2>/dev/null || launchctl unload "$plist_file" 2>/dev/null || true
        if ! launchctl bootstrap "$domain" "$plist_file" 2>/dev/null; then
            launchctl load "$plist_file"
        fi
    else
        log_info "$service_name: not loaded; definition written for the next 'make start'"
    fi
}

withdraw_docs_watch_launchd() {
    local domain
    domain="$(launchd_domain)"
    local plist_file
    plist_file="$(launchd_plist_path "$DOCS_WATCH_LABEL")"
    local state_before
    local state_after
    local definition_present=false

    if ! docs_watch_definition_type_is_safe "$plist_file" "$DOCS_WATCH_LABEL"; then
        return 1
    fi
    if [ -f "$plist_file" ]; then
        definition_present=true
    fi
    if ! state_before="$(launchd_docs_watch_state "$domain")"; then
        return 1
    fi
    log_info "docs-watch launchd manager answer before installation reconciliation: $state_before ($domain/$DOCS_WATCH_LABEL)"

    if [ "$state_before" = "loaded" ]; then
        if ! launchctl bootout "$domain/$DOCS_WATCH_LABEL"; then
            log_error "docs-watch: launchd refused to unload $DOCS_WATCH_LABEL in $domain; resolve the manager refusal and rerun make install."
            return 1
        fi
    fi
    if [ "$definition_present" = true ] && ! rm -f "$plist_file"; then
        log_error "docs-watch: could not remove the launchd definition for $DOCS_WATCH_LABEL; resolve the file error and rerun make install."
        return 1
    fi
    if [ -e "$plist_file" ] || [ -L "$plist_file" ]; then
        log_error "docs-watch: the launchd definition for $DOCS_WATCH_LABEL is still present; remove the remaining definition and rerun make install."
        return 1
    fi
    if ! state_after="$(wait_for_launchd_docs_watch_unloaded "$domain" "$DOCS_WATCH_WITHDRAW_SETTLE_SECONDS")"; then
        return 1
    fi
    log_info "docs-watch launchd manager answer after installation reconciliation: $state_after ($domain/$DOCS_WATCH_LABEL)"
    if [ "$state_after" != "not-loaded" ]; then
        log_error "docs-watch: $DOCS_WATCH_LABEL remains loaded after installation reconciliation; resolve the launchd state and rerun make install."
        return 1
    fi
    if [ "$definition_present" = false ] && [ "$state_before" = "$state_after" ]; then
        log_info "No docs-watch launchd unit to withdraw; manager state is unchanged."
    elif [ "$state_before" = "loaded" ]; then
        log_info "Withdrew the docs-watch launchd unit $DOCS_WATCH_LABEL."
    else
        log_info "Removed the stale docs-watch launchd definition for $DOCS_WATCH_LABEL."
    fi
}

withdraw_docs_watch_systemd() {
    local state_before
    local state_after
    local definition_present=false

    if ! docs_watch_definition_type_is_safe "$_DOCS_WATCH_SYSTEMD_PATH" "$_DOCS_WATCH_SYSTEMD_UNIT"; then
        return 1
    fi
    if [ -f "$_DOCS_WATCH_SYSTEMD_PATH" ]; then
        definition_present=true
    fi
    if ! state_before="$(systemd_docs_watch_state)"; then
        return 1
    fi
    log_info "docs-watch system manager answer before installation reconciliation: $state_before ($_DOCS_WATCH_SYSTEMD_UNIT)"

    if [ "$state_before" = "loaded" ]; then
        if ! _tc_sudo "stop and disable the docs-watch systemd unit" systemctl --system disable --now "$_DOCS_WATCH_SYSTEMD_UNIT"; then
            log_error "docs-watch: systemd refused to stop and disable $_DOCS_WATCH_SYSTEMD_UNIT; resolve the manager refusal and rerun make install."
            return 1
        fi
    fi
    if [ "$definition_present" = true ] && ! _tc_sudo "remove the docs-watch systemd definition" rm -f "$_DOCS_WATCH_SYSTEMD_PATH"; then
        log_error "docs-watch: could not remove the systemd definition for $_DOCS_WATCH_SYSTEMD_UNIT; resolve the file error and rerun make install."
        return 1
    fi
    if [ -e "$_DOCS_WATCH_SYSTEMD_PATH" ] || [ -L "$_DOCS_WATCH_SYSTEMD_PATH" ]; then
        log_error "docs-watch: the systemd definition $_DOCS_WATCH_SYSTEMD_UNIT is still present; remove the remaining definition and rerun make install."
        return 1
    fi
    if [ "$definition_present" = true ] || [ "$state_before" = "loaded" ]; then
        if ! _tc_sudo "reload systemd after removing the docs-watch unit" systemctl --system daemon-reload; then
            log_error "docs-watch: systemd daemon-reload failed after removing $_DOCS_WATCH_SYSTEMD_UNIT; resolve the manager error and rerun make install."
            return 1
        fi
    fi
    if ! state_after="$(systemd_docs_watch_state)"; then
        return 1
    fi
    log_info "docs-watch system manager answer after installation reconciliation: $state_after ($_DOCS_WATCH_SYSTEMD_UNIT)"
    if [ "$state_after" != "not-found" ]; then
        log_error "docs-watch: $_DOCS_WATCH_SYSTEMD_UNIT remains loaded after installation reconciliation; resolve the systemd state and rerun make install."
        return 1
    fi
    if [ "$definition_present" = false ] && [ "$state_before" = "$state_after" ]; then
        log_info "No docs-watch systemd unit to withdraw; manager state is unchanged."
    elif [ "$state_before" = "loaded" ]; then
        log_info "Withdrew the docs-watch systemd unit $_DOCS_WATCH_SYSTEMD_UNIT."
    else
        log_info "Removed the stale docs-watch systemd definition $_DOCS_WATCH_SYSTEMD_UNIT."
    fi
}

# Names the legacy docs-watch unit when installation would withdraw it, and withdraws nothing.
report_docs_watch_withdrawal_due() {
    case "$PLATFORM" in
        macos)
            if [ -f "$(launchd_plist_path "$DOCS_WATCH_LABEL")" ] || launchctl print "$(launchd_domain)/$DOCS_WATCH_LABEL" >/dev/null 2>&1; then
                printf 'legacy docs-watch launchd unit is due for withdrawal: %s\n' "$DOCS_WATCH_LABEL"
            fi
            ;;
        linux)
            if [ -f "$_DOCS_WATCH_SYSTEMD_PATH" ] || [ "$(systemctl show --system --property=LoadState --value "$_DOCS_WATCH_SYSTEMD_UNIT" 2>/dev/null)" = loaded ]; then
                printf 'legacy docs-watch systemd unit is due for withdrawal: %s\n' "$_DOCS_WATCH_SYSTEMD_UNIT"
            fi
            ;;
    esac
}

withdraw_docs_watch_service() {
    if defer_service_changes; then
        report_docs_watch_withdrawal_due
        return 0
    fi
    case "$PLATFORM" in
        macos)
            withdraw_docs_watch_launchd
            ;;
        linux)
            withdraw_docs_watch_systemd
            ;;
        *)
            log_error "docs-watch: unsupported service manager platform $PLATFORM"
            return 1
            ;;
    esac
}

# The port the ingress receiver listens on, or nothing when the receiver does not serve this computer's ingress.
ingress_receiver_port() {
    local errors
    errors="$(mktemp)"
    if ! PYTHONPATH="$PROJECT_ROOT" "$PROJECT_ROOT/.venv/bin/python" -c '
from teleclaude.config.machine import config
print(config.api.tcp_port if config.computer.is_ingress_node and config.computer.ingress_receiver else "")' 2>"$errors"; then
        log_error "Could not read whether this computer is the ingress: $(tail -n 3 "$errors")"
        rm -f "$errors"
        return 1
    fi
    rm -f "$errors"
}

# Remove the ingress receiver's units: this computer is no longer the ingress, or a release without the
# receiver becomes active.
withdraw_ingress_receiver() {
    local name="$INGRESS_RECEIVER_LABEL"
    case "$PLATFORM" in
        linux)
            local socket_file="/etc/systemd/system/${name}.socket"
            local service_file="/etc/systemd/system/${name}.service"
            [ -f "$socket_file" ] || [ -f "$service_file" ] || return 0
            _tc_sudo "stop the ingress receiver" systemctl disable --now "${name}.socket" "${name}.service" || return 1
            _tc_sudo "remove the ingress receiver units" rm -f "$socket_file" "$service_file" || return 1
            _tc_sudo "reload systemd after removing the ingress receiver" systemctl daemon-reload || return 1
            ;;
        macos)
            local plist_file
            plist_file="$(launchd_plist_path "$name")"
            [ -f "$plist_file" ] || return 0
            if is_launchd_unit_loaded "$name"; then
                launchctl bootout "$(launchd_domain)/$name" || return 1
            fi
            rm -f "$plist_file" || return 1
            ;;
    esac
    log_info "Withdrew the ingress receiver's units"
}

install_systemd_ingress_receiver() {
    local port="$1"
    local name="$INGRESS_RECEIVER_LABEL"
    local socket_file="/etc/systemd/system/${name}.socket"
    local service_file="/etc/systemd/system/${name}.service"
    local service_path="$SERVICE_ROOT/.venv/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

    local rendered_socket rendered_service
    rendered_socket="$(mktemp)"
    rendered_service="$(mktemp)"
    render_template_or_die "$PROJECT_ROOT/templates/${name}.socket" "$rendered_socket" "PORT=$port"
    render_template_or_die "$PROJECT_ROOT/templates/${name}.service" "$rendered_service" \
        "PYTHON_PATH=$SERVICE_ROOT/.venv/bin/python" "WORKING_DIR=$SERVICE_ROOT" "PATH=$service_path" "XDG_DATA_HOME=$SERVICE_DATA_HOME"

    local socket_deployed=false
    local service_deployed=false
    if deploy_or_die "$rendered_socket" "$socket_file" --sudo; then
        socket_deployed=true
    fi
    if deploy_or_die "$rendered_service" "$service_file" --sudo; then
        service_deployed=true
    fi
    rm -f "$rendered_socket" "$rendered_service"
    # On demand or under --check the differences are named above and nothing is started.
    defer_service_changes && return 0

    # Each step returns its failure itself: callers run this under a condition, where errexit does not apply.
    if $socket_deployed || $service_deployed; then
        log_info "Deployed ingress receiver systemd definition(s)"
        _tc_sudo "reload systemd after deploying the ingress receiver" systemctl daemon-reload || return 1
    fi
    if $socket_deployed && systemctl is-active --quiet "${name}.socket"; then
        # A socket whose service runs refuses a restart; the service starts again on the new socket.
        _tc_sudo "stop ${name}.service" systemctl stop "${name}.service" || return 1
        _tc_sudo "restart ${name}.socket" systemctl restart "${name}.socket" || return 1
    fi
    if ! systemctl is-enabled --quiet "${name}.socket" || ! systemctl is-active --quiet "${name}.socket"; then
        _tc_sudo "enable ${name}.socket" systemctl enable --now "${name}.socket" || return 1
    fi
    if $service_deployed && systemctl is-active --quiet "${name}.service"; then
        _tc_sudo "restart ${name}.service" systemctl restart "${name}.service" || return 1
    fi
    if ! systemctl is-enabled --quiet "${name}.service" || ! systemctl is-active --quiet "${name}.service"; then
        _tc_sudo "enable ${name}.service" systemctl enable --now "${name}.service" || return 1
    fi
}

install_launchd_ingress_receiver() {
    local port="$1"
    local name="$INGRESS_RECEIVER_LABEL"
    local plist_file
    plist_file="$(launchd_plist_path "$name")"

    mkdir -p "$HOME/Library/LaunchAgents"
    local launchd_path
    launchd_path="$(launchd_path_env)"
    local rendered_file
    rendered_file="$(mktemp)"
    render_template_or_die "$PROJECT_ROOT/templates/${name}.plist" "$rendered_file" \
        "PYTHON_PATH=$SERVICE_ROOT/.venv/bin/python" "WORKING_DIR=$SERVICE_ROOT" "PATH=$launchd_path" \
        "XDG_DATA_HOME=$SERVICE_DATA_HOME" "PORT=$port"

    local deployed=false
    if deploy_or_die "$rendered_file" "$plist_file"; then
        deployed=true
    fi
    rm -f "$rendered_file"
    # On demand or under --check the difference is named above and nothing is loaded.
    defer_service_changes && return 0

    local domain
    domain="$(launchd_domain)"
    # Each step returns its failure itself: callers run this under a condition, where errexit does not apply.
    if is_launchd_unit_loaded "$name"; then
        $deployed || return 0
        # A changed definition reloads the job, which closes and reopens its socket.
        launchctl bootout "$domain/$name" || return 1
    fi
    launchctl bootstrap "$domain" "$plist_file" || return 1
    log_info "Loaded ingress receiver: $plist_file"
}

# Whether deploying or withdrawing would change which of the daemon and the receiver serves the ingress.
ingress_receiver_change_pending() {
    local port installed=false wanted=false
    port="$(ingress_receiver_port)" || return 1
    [ -n "$port" ] && wanted=true
    case "$PLATFORM" in
        linux) [ -f "/etc/systemd/system/${INGRESS_RECEIVER_LABEL}.socket" ] && installed=true ;;
        macos) [ -f "$(launchd_plist_path "$INGRESS_RECEIVER_LABEL")" ] && installed=true ;;
    esac
    [ "$wanted" != "$installed" ]
}

# The ingress receiver's units exist only on the ingress computer (single-ingress-webhook-termination).
install_ingress_receiver() {
    local port
    # An unreadable configuration withdraws nothing and deploys nothing, and fails the comparison.
    port="$(ingress_receiver_port)" || return 1
    if [ -z "$port" ]; then
        defer_service_changes || withdraw_ingress_receiver
        return
    fi
    case "$PLATFORM" in
        linux) install_systemd_ingress_receiver "$port" ;;
        macos) install_launchd_ingress_receiver "$port" ;;
    esac
}

install_service() {
    case "$PLATFORM" in
        linux)
            install_systemd_service
            install_systemd_cron_service
            ;;
        macos)
            install_launchd_service
            install_launchd_cron_service
            ;;
    esac
    # Deployment runs before the daemon starts (bin/daemon-control.sh start_daemon); a comparison names its
    # differences here.
    if defer_service_changes; then
        install_ingress_receiver
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -euo pipefail
    if [ "${1:-}" = "--check" ]; then
        TC_SERVICE_DEFINITION_CHECK=true
        install_service
        withdraw_docs_watch_service
    else
        install_service
    fi
fi
