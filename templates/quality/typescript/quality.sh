#!/usr/bin/env bash
# Blessed TypeScript quality entrypoint.
#
# Owns the scoped lint/format behavior behind `make lint` / `make format` so the
# Makefile recipe stays a single delegation line. The project owns this file once
# copied in: it invokes only the project's own tools and has no TeleClaude
# dependency, so `make lint` works standalone.
#
# Scope contract (software-development/design/project-toolchain): when FILES_FROM
# is set it names a temp file of NUL-terminated paths. Only those paths are
# checked, each tool receives only the paths it actually owns, and a tool whose
# bucket is empty does not run at all. With no FILES_FROM, everything runs.
set -euo pipefail

usage() {
    printf 'Usage: %s {lint|format}\n' "$0" >&2
    exit 2
}

SCOPED=0
PATHS=()
LINT=()
FORMAT=()
TS=()
FULL=0

read_scope() {
    local files_from="${FILES_FROM:-}"
    [ -n "$files_from" ] || return 0
    [ -f "$files_from" ] || return 0
    SCOPED=1
    local path
    while IFS= read -r -d "" path; do
        PATHS+=("$path")
    done <"$files_from"
}

# Run the project's package manager. Lockfile decides; pnpm is the blessed default.
pm_exec() {
    if [ -f pnpm-lock.yaml ] && command -v pnpm >/dev/null 2>&1; then
        pnpm exec "$@"
    elif [ -f yarn.lock ] && command -v yarn >/dev/null 2>&1; then
        yarn exec "$@"
    elif [ -f bun.lockb ] && command -v bun >/dev/null 2>&1; then
        bun x "$@"
    else
        npx --no-install "$@"
    fi
}

uses_biome() {
    [ -f biome.json ] || [ -f biome.jsonc ]
}

is_script() {
    case "$1" in
    *.ts | *.tsx | *.mts | *.cts | *.js | *.jsx | *.mjs | *.cjs) return 0 ;;
    esac
    return 1
}

# Which paths each tool owns. Handing a linter a file type it does not handle is
# an error, not a no-op, so the buckets are per-tool rather than one "sources"
# list: biome covers scripts plus json/css; eslint covers scripts only; prettier
# additionally owns the prose and config formats biome declines.
owns_lint() {
    is_script "$1" && return 0
    if uses_biome; then
        case "$1" in
        *.json | *.jsonc | *.css) return 0 ;;
        esac
    fi
    return 1
}

owns_format() {
    if uses_biome; then
        owns_lint "$1"
        return
    fi
    is_script "$1" && return 0
    case "$1" in
    *.json | *.css | *.md | *.yml | *.yaml) return 0 ;;
    esac
    return 1
}

# tsc -b resolves the whole project graph and cannot take a file subset. It is
# therefore all-or-nothing: run it when the scope contains TypeScript, skip it
# entirely when it does not. Never widen a non-TS scope back to the whole tree.
run_typecheck() {
    [ -f tsconfig.json ] || return 0
    pm_exec tsc -b --pretty false
}

collect() {
    local path
    for path in ${PATHS[@]+"${PATHS[@]}"}; do
        if owns_lint "$path"; then LINT+=("$path"); fi
        if owns_format "$path"; then FORMAT+=("$path"); fi
        case "$path" in
        *.ts | *.tsx | *.mts | *.cts) TS+=("$path") ;;
        esac
        # A config change invalidates file-level scoping for every tool it governs.
        case "$path" in
        tsconfig*.json | package.json) FULL=1 ;;
        biome.json | biome.jsonc | eslint.config.* | .prettierrc*) FULL=1 ;;
        esac
    done
}

lint_paths() {
    if uses_biome; then
        pm_exec biome check --no-errors-on-unmatched "$@"
    else
        pm_exec eslint "$@"
    fi
}

format_paths() {
    if uses_biome; then
        pm_exec biome format --write --no-errors-on-unmatched "$@"
    else
        pm_exec prettier --write "$@"
    fi
}

main() {
    [ $# -ge 1 ] || usage
    local action="$1"

    read_scope
    if [ "$SCOPED" -eq 1 ]; then
        collect
    fi
    local full=0
    if [ "$SCOPED" -eq 0 ] || [ "$FULL" -eq 1 ]; then
        full=1
    fi

    case "$action" in
    lint)
        if [ "$full" -eq 1 ]; then
            lint_paths .
            run_typecheck
        else
            if [ "${#LINT[@]}" -gt 0 ]; then
                lint_paths "${LINT[@]}"
            fi
            if [ "${#TS[@]}" -gt 0 ]; then
                run_typecheck
            fi
        fi
        echo "✓ Lint checks passed"
        ;;
    format)
        if [ "$full" -eq 1 ]; then
            format_paths .
        elif [ "${#FORMAT[@]}" -gt 0 ]; then
            format_paths "${FORMAT[@]}"
        fi
        echo "✓ Code formatted"
        ;;
    *)
        usage
        ;;
    esac
}

main "$@"
