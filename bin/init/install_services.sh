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

# Project root: prefer a value the caller already resolved (PROJECT_ROOT),
# then bin/install.sh's INSTALL_DIR, then this file's own location.
if [ -n "${PROJECT_ROOT:-}" ]; then
    PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
elif [ -n "${INSTALL_DIR:-}" ]; then
    PROJECT_ROOT="$(cd "$INSTALL_DIR" && pwd)"
else
    PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

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
if [ "$PLATFORM" = "macos" ]; then
    V1_DAEMON_LABEL="ai.instrukt.teleclaude.daemon"
    DOCS_WATCH_LABEL="ai.instrukt.teleclaude.docs-watch"
    CRON_LABEL="ai.instrukt.teleclaude.cron"
    SERVICE_LABEL="$V1_DAEMON_LABEL"
    SERVICE_PATH="$HOME/Library/LaunchAgents/$SERVICE_LABEL.plist"
else
    SERVICE_LABEL="teleclaude"
    SERVICE_PATH="/etc/systemd/system/$SERVICE_LABEL.service"
fi

managed_launchd_labels() {
    printf '%s\n' "$V1_DAEMON_LABEL"
    printf '%s\n' "$DOCS_WATCH_LABEL"
    printf '%s\n' "$CRON_LABEL"
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
    # See project/spec/agent-shell-path (Implementation 2 — the daemon).
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

    # Every call site below invokes this function (via deploy_or_die) as the
    # condition of an `if`/`!`, which suppresses `set -e` for the entire call
    # — a failed cp would otherwise fall through to the unconditional
    # `return 0` and be reported as a successful "changed" deploy while the
    # target keeps its stale content. Check the write explicitly instead.
    if [ "$use_sudo" = "--sudo" ]; then
        if ! sudo cp "$rendered_file" "$target_path"; then
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

install_systemd_service() {
    local service_name="teleclaude"
    local service_file="/etc/systemd/system/${service_name}.service"
    local path_file="/etc/systemd/system/${service_name}-config.path"

    # Create wrapper script for SSH agent support
    cat > "$PROJECT_ROOT/bin/teleclaude-wrapper.sh" <<'EOF'
#!/bin/bash
# Resolve project root from this script location so it works under systemd.
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Source keychain SSH agent environment
if [ -f ~/.keychain/$(hostname)-sh ]; then
    source ~/.keychain/$(hostname)-sh
fi
# Execute daemon
exec $PROJECT_ROOT/.venv/bin/python -m teleclaude.daemon
EOF
    chmod +x "$PROJECT_ROOT/bin/teleclaude-wrapper.sh"

    local rendered_service
    rendered_service="$(mktemp)"
    cat > "$rendered_service" <<EOF
[Unit]
Description=TeleClaude Terminal Bridge Daemon
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_ROOT
Environment="PATH=$PROJECT_ROOT/.venv/bin:$HOME/.npm-global/bin:$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin"
# SSH_AUTH_SOCK sourced from keychain in wrapper
ExecStart=$PROJECT_ROOT/bin/teleclaude-wrapper.sh
Restart=on-failure
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
PathModified=$PROJECT_ROOT/config.yml
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
    sudo systemctl daemon-reload

    if $service_deployed; then
        if sudo systemctl is-active --quiet "$service_name"; then
            sudo systemctl restart "$service_name"
        else
            sudo systemctl enable "$service_name"
        fi
    fi

    if $path_deployed; then
        if sudo systemctl is-active --quiet "${service_name}-config.path"; then
            sudo systemctl restart "${service_name}-config.path"
        else
            sudo systemctl enable "${service_name}-config.path"
        fi
    fi
}

install_systemd_docs_watch_service() {
    local service_name="teleclaude-docs-watch"
    local service_file="/etc/systemd/system/${service_name}.service"
    local template_file="$PROJECT_ROOT/templates/teleclaude-docs-watch.service"
    local command="uv run --quiet --project $PROJECT_ROOT -m teleclaude.cli.watch"
    local service_path="$PROJECT_ROOT/.venv/bin:$HOME/.npm-global/bin:$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin"

    if [ ! -f "$template_file" ]; then
        log_error "Template file not found: $template_file"
        exit 1
    fi

    local rendered_file
    rendered_file="$(mktemp)"
    sed \
        -e "s|{{COMMAND}}|$command|g" \
        -e "s|{{WORKING_DIR}}|$PROJECT_ROOT|g" \
        -e "s|{{USER}}|$USER|g" \
        -e "s|{{PATH}}|$service_path|g" \
        "$template_file" > "$rendered_file"

    if ! deploy_or_die "$rendered_file" "$service_file" --sudo; then
        rm -f "$rendered_file"
        return 0
    fi
    rm -f "$rendered_file"

    log_info "Deployed docs watcher systemd service"
    sudo systemctl daemon-reload
    if sudo systemctl is-active --quiet "$service_name"; then
        sudo systemctl restart "$service_name"
    else
        sudo systemctl enable "$service_name"
    fi
}

install_systemd_cron_service() {
    local service_name="teleclaude-cron"
    local service_file="/etc/systemd/system/${service_name}.service"
    local timer_file="/etc/systemd/system/${service_name}.timer"
    local service_template="$PROJECT_ROOT/templates/teleclaude-cron.service"
    local timer_template="$PROJECT_ROOT/templates/teleclaude-cron.timer"
    # Run via the project venv interpreter (not `uv run`): the script's inline
    # PEP-723 metadata forces `uv run` into an isolated env without the project's
    # dependencies. Mirrors the launchd cron unit and the daemon service.
    local command="$PROJECT_ROOT/.venv/bin/python scripts/cron_runner.py"
    local service_path="$PROJECT_ROOT/.venv/bin:$HOME/.npm-global/bin:$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin"

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
    sed \
        -e "s|{{COMMAND}}|$command|g" \
        -e "s|{{WORKING_DIR}}|$PROJECT_ROOT|g" \
        -e "s|{{USER}}|$USER|g" \
        -e "s|{{PATH}}|$service_path|g" \
        "$service_template" > "$rendered_service"

    local service_deployed=false
    local timer_deployed=false

    if deploy_or_die "$rendered_service" "$service_file" --sudo; then
        service_deployed=true
    fi
    rm -f "$rendered_service"

    # The timer template carries no markers; deploy it directly.
    if deploy_or_die "$timer_template" "$timer_file" --sudo; then
        timer_deployed=true
    fi

    if ! $service_deployed && ! $timer_deployed; then
        return 0
    fi

    log_info "Deployed cron systemd service/timer"
    sudo systemctl daemon-reload

    if sudo systemctl is-active --quiet "${service_name}.timer"; then
        sudo systemctl restart "${service_name}.timer"
    else
        sudo systemctl enable "${service_name}.timer"
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
    sed -e "s|{{PYTHON_PATH}}|$PROJECT_ROOT/.venv/bin/python|g" \
        -e "s|{{WORKING_DIR}}|$PROJECT_ROOT|g" \
        -e "s|{{PATH}}|$launchd_path|g" \
        "$template_file" > "$rendered_file"

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

install_launchd_docs_watch_service() {
    local service_name="$DOCS_WATCH_LABEL"
    local plist_file
    plist_file="$(launchd_plist_path "$service_name")"
    local template_file="$PROJECT_ROOT/templates/ai.instrukt.teleclaude.docs-watch.plist"

    mkdir -p "$HOME/Library/LaunchAgents"

    if [ ! -f "$template_file" ]; then
        log_error "Template file not found: $template_file"
        exit 1
    fi

    local launchd_path
    launchd_path="$(launchd_path_env)"
    local command="uv run --quiet --project $PROJECT_ROOT -m teleclaude.cli.watch"

    local rendered_file
    rendered_file="$(mktemp)"
    sed -e "s|{{LABEL}}|$service_name|g" \
        -e "s|{{COMMAND}}|$command|g" \
        -e "s|{{WORKING_DIR}}|$PROJECT_ROOT|g" \
        -e "s|{{PATH}}|$launchd_path|g" \
        "$template_file" > "$rendered_file"

    if ! deploy_or_die "$rendered_file" "$plist_file"; then
        rm -f "$rendered_file"
        return 0
    fi
    rm -f "$rendered_file"

    log_info "Deployed docs watcher plist: $plist_file"

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
    sed -e "s|{{PYTHON_PATH}}|$PROJECT_ROOT/.venv/bin/python|g" \
        -e "s|{{WORKING_DIR}}|$PROJECT_ROOT|g" \
        -e "s|{{PATH}}|$launchd_path|g" \
        -e "s|{{HOME}}|$HOME|g" \
        "$template_file" > "$rendered_file"

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

install_service() {
    case "$PLATFORM" in
        linux)
            install_systemd_service
            install_systemd_docs_watch_service
            install_systemd_cron_service
            ;;
        macos)
            install_launchd_service
            install_launchd_docs_watch_service
            install_launchd_cron_service
            ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -euo pipefail
    install_service
fi
