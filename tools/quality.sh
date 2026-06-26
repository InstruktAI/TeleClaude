#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s {lint|format|test}\n' "$0" >&2
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

declare -a PATHS=()
SCOPED=0

read_scope() {
    local files_from="${FILES_FROM:-}"
    if [ -n "$files_from" ]; then
        SCOPED=1
        while IFS= read -r -d '' path; do
            PATHS+=("$path")
        done < "$files_from"
    fi
}

declare -a LEG_LABELS=()
declare -a LEG_FILES=()
declare -a LEG_PIDS=()

start_leg() {
    local label="$1"
    shift
    local output
    output="$(mktemp "${TMPDIR:-/tmp}/teleclaude-quality.XXXXXX")"
    LEG_LABELS+=("$label")
    LEG_FILES+=("$output")
    ("$@") > "$output" 2>&1 &
    LEG_PIDS+=("$!")
}

run_legs() {
    local status=0
    local idx pid code label output

    if [ "${#LEG_PIDS[@]}" -eq 0 ]; then
        return 0
    fi

    for idx in "${!LEG_PIDS[@]}"; do
        pid="${LEG_PIDS[$idx]}"
        if wait "$pid"; then
            code=0
        else
            code=$?
            status=1
        fi
        LEG_PIDS[idx]="$code"
    done

    for idx in "${!LEG_FILES[@]}"; do
        label="${LEG_LABELS[$idx]}"
        output="${LEG_FILES[$idx]}"
        code="${LEG_PIDS[$idx]}"
        printf '\n==> %s' "$label"
        if [ "$code" -eq 0 ]; then
            printf ' (ok)\n'
        else
            printf ' (failed: %s)\n' "$code"
        fi
        if [ -s "$output" ]; then
            cat "$output"
            printf '\n'
        fi
        rm -f "$output"
    done

    LEG_LABELS=()
    LEG_FILES=()
    LEG_PIDS=()
    return "$status"
}

run_frontend_format() {
    if command -v pnpm >/dev/null 2>&1; then
        pnpm exec prettier --write "$@"
    else
        npx --yes prettier --write "$@"
    fi
}

run_frontend_lint() {
    if command -v pnpm >/dev/null 2>&1; then
        pnpm exec eslint "$@" && pnpm exec tsc --noEmit
    else
        npx --yes eslint "$@" && npx --yes tsc --noEmit
    fi
}

run_jscpd() {
    if [ "$#" -gt 0 ]; then
        npx --yes jscpd --min-lines 25 --min-tokens 150 --mode strict --exit-code 1 --ignore "**/migrations/**" "$@"
    fi
}

array_contains() {
    local needle="$1"
    shift
    local item
    for item in "$@"; do
        if [ "$item" = "$needle" ]; then
            return 0
        fi
    done
    return 1
}

nearest_manifest_for_path() {
    local path="$1"
    local dir
    dir="${path%/*}"
    if [ "$dir" = "$path" ] || [ -z "$dir" ]; then
        dir="."
    fi

    while true; do
        if [ -f "$dir/Cargo.toml" ]; then
            printf '%s/Cargo.toml\n' "$dir"
            return 0
        fi
        if [ "$dir" = "." ] || [ "$dir" = "/" ]; then
            return 1
        fi
        dir="${dir%/*}"
        if [ -z "$dir" ]; then
            dir="."
        fi
    done
}

rust_manifests_from_paths() {
    local path manifest
    RUST_WORKSPACE=0
    RUST_MANIFESTS=()
    for path in "$@"; do
        case "$path" in
            Cargo.toml|Cargo.lock)
                RUST_WORKSPACE=1
                continue
                ;;
            *.rs|*/Cargo.toml) ;;
            *) continue ;;
        esac
        if manifest="$(nearest_manifest_for_path "$path")"; then
            if [ "$manifest" = "./Cargo.toml" ] || [ "$manifest" = "Cargo.toml" ]; then
                RUST_WORKSPACE=1
            elif ! array_contains "$manifest" "${RUST_MANIFESTS[@]}"; then
                RUST_MANIFESTS+=("$manifest")
            fi
        fi
    done
}

run_rust_fmt_scoped() {
    rust_manifests_from_paths "$@"
    if [ "$RUST_WORKSPACE" -eq 1 ]; then
        cargo fmt --all
    else
        local manifest
        for manifest in "${RUST_MANIFESTS[@]}"; do
            cargo fmt --manifest-path "$manifest"
        done
    fi
}

run_rust_clippy_scoped() {
    rust_manifests_from_paths "$@"
    if [ "$RUST_WORKSPACE" -eq 1 ]; then
        cargo clippy --workspace --all-targets -- -D warnings
    else
        local manifest
        for manifest in "${RUST_MANIFESTS[@]}"; do
            cargo clippy --manifest-path "$manifest" --all-targets -- -D warnings
        done
    fi
}

format_python() {
    uv run ruff check --fix "$@"
    uv run ruff format "$@"
}

format_root_prettier() {
    npx --yes prettier --write "$@"
}

format_frontend() {
    (cd frontend && run_frontend_format "$@")
}

format_full() {
    local -a prettier_targets=()
    local p
    start_leg "python format" format_python .
    for p in README.md AGENTS.md; do
        [ -f "$p" ] && prettier_targets+=("$p")
    done
    [ -d docs ] && prettier_targets+=("docs/**/*.md")
    if [ "${#prettier_targets[@]}" -gt 0 ]; then
        start_leg "root prettier" format_root_prettier "${prettier_targets[@]}"
    fi
    if [ -d frontend ] && [ -f frontend/package.json ]; then
        start_leg "frontend prettier" format_frontend .
    fi
    if [ -f Cargo.toml ]; then
        start_leg "rust fmt" cargo fmt --all
    fi
    run_legs
}

format_scoped() {
    local -a py=()
    local -a prettier_root=()
    local -a prettier_frontend=()
    local -a rust_inputs=()
    local path

    for path in "${PATHS[@]}"; do
        case "$path" in *.py) py+=("$path") ;; esac
        case "$path" in
            frontend/*)
                case "$path" in
                    *.ts|*.tsx|*.js|*.jsx|*.mjs|*.cjs|*.json|*.css|*.md|*.yml|*.yaml)
                        prettier_frontend+=("${path#frontend/}")
                        ;;
                esac
                ;;
            *.md|*.json|*.yml|*.yaml)
                prettier_root+=("$path")
                ;;
        esac
        case "$path" in *.rs|Cargo.toml|Cargo.lock|*/Cargo.toml) rust_inputs+=("$path") ;; esac
    done

    [ "${#py[@]}" -gt 0 ] && start_leg "python format" format_python "${py[@]}"
    [ "${#prettier_root[@]}" -gt 0 ] && start_leg "root prettier" format_root_prettier "${prettier_root[@]}"
    if [ "${#prettier_frontend[@]}" -gt 0 ] && [ -d frontend ]; then
        start_leg "frontend prettier" format_frontend "${prettier_frontend[@]}"
    fi
    if [ "${#rust_inputs[@]}" -gt 0 ] && [ -f Cargo.toml ]; then
        start_leg "rust fmt" run_rust_fmt_scoped "${rust_inputs[@]}"
    fi
    run_legs
}

lint_full() {
    start_leg "ruff check" uv run ruff check .
    start_leg "ruff format check" uv run ruff format --check .
    start_leg "pyright" uv run pyright
    start_leg "mypy" uv run mypy

    local -a jscpd_targets=()
    local p
    for p in teleclaude tools; do
        [ -e "$p" ] && jscpd_targets+=("$p")
    done
    [ "${#jscpd_targets[@]}" -gt 0 ] && start_leg "jscpd" run_jscpd "${jscpd_targets[@]}"
    if [ -d frontend ] && [ -f frontend/package.json ]; then
        start_leg "frontend lint" lint_frontend_full
    fi
    if [ -f Cargo.toml ]; then
        start_leg "cargo clippy" cargo clippy --workspace --all-targets -- -D warnings
    fi
    run_legs
}

lint_frontend_full() {
    (cd frontend && run_frontend_lint .)
}

lint_frontend_scoped() {
    (cd frontend && run_frontend_lint "$@")
}

lint_scoped() {
    local -a py=()
    local -a ts=()
    local -a rust_inputs=()
    local path
    local py_full=0
    local ts_full=0

    for path in "${PATHS[@]}"; do
        case "$path" in
            *.py) py+=("$path") ;;
            pyproject.toml|mypy.ini|pyrightconfig.json) py_full=1 ;;
        esac
        case "$path" in
            frontend/*.ts|frontend/*.tsx|frontend/*.js|frontend/*.jsx|frontend/*.mjs|frontend/*.cjs)
                ts+=("${path#frontend/}")
                ;;
            frontend/package.json|frontend/tsconfig*.json|frontend/eslint.config.*|frontend/vitest.config.*)
                ts_full=1
                ;;
        esac
        case "$path" in *.rs|Cargo.toml|Cargo.lock|*/Cargo.toml) rust_inputs+=("$path") ;; esac
    done

    if [ "$py_full" -eq 1 ]; then
        start_leg "ruff check" uv run ruff check .
        start_leg "ruff format check" uv run ruff format --check .
        start_leg "pyright" uv run pyright
        start_leg "mypy" uv run mypy
        local -a jscpd_targets=()
        for path in teleclaude tools; do
            [ -e "$path" ] && jscpd_targets+=("$path")
        done
        [ "${#jscpd_targets[@]}" -gt 0 ] && start_leg "jscpd" run_jscpd "${jscpd_targets[@]}"
    elif [ "${#py[@]}" -gt 0 ]; then
        start_leg "ruff check" uv run ruff check "${py[@]}"
        start_leg "ruff format check" uv run ruff format --check "${py[@]}"
        start_leg "pyright" uv run pyright "${py[@]}"
        start_leg "mypy" uv run mypy "${py[@]}"
        start_leg "jscpd" run_jscpd "${py[@]}"
    fi

    if [ -d frontend ] && [ -f frontend/package.json ]; then
        if [ "$ts_full" -eq 1 ]; then
            start_leg "frontend lint" lint_frontend_full
        elif [ "${#ts[@]}" -gt 0 ]; then
            start_leg "frontend lint" lint_frontend_scoped "${ts[@]}"
        fi
    fi
    if [ "${#rust_inputs[@]}" -gt 0 ] && [ -f Cargo.toml ]; then
        start_leg "cargo clippy" run_rust_clippy_scoped "${rust_inputs[@]}"
    fi
    run_legs
}

run_tests() {
    local -a pytest_args=()
    if [ -n "${SNAPSHOT_UPDATE:-}" ]; then
        pytest_args+=("--snapshot-update")
    fi

    uv run pytest "${pytest_args[@]}"

    if [ -d frontend ] && [ -f frontend/package.json ]; then
        if [ -n "${SNAPSHOT_UPDATE:-}" ]; then
            (cd frontend && { if command -v pnpm >/dev/null 2>&1; then pnpm test -- -u; else npm test -- -u; fi; })
        else
            (cd frontend && { if command -v pnpm >/dev/null 2>&1; then pnpm test; else npm test; fi; })
        fi
    fi

    if [ -f Cargo.toml ]; then
        cargo test --workspace --lib
    fi

    if [ -z "${CI:-}" ]; then
        make test-meta
    fi
}

main() {
    if [ "$#" -ne 1 ]; then
        usage
        exit 2
    fi

    read_scope

    case "$1" in
        format)
            if [ "$SCOPED" -eq 0 ]; then format_full; else format_scoped; fi
            ;;
        lint)
            if [ "$SCOPED" -eq 0 ]; then lint_full; else lint_scoped; fi
            ;;
        test)
            run_tests
            ;;
        *)
            usage
            exit 2
            ;;
    esac
}

main "$@"
