#!/usr/bin/env bash
# Verify all CLI commands and subcommands respond to -h without error.
# Triggered by pre-commit when CLI modules are touched.

set -euo pipefail

# timeout reserves this status for a deadline, not a CLI-help verdict.
readonly TIMEOUT_KILL_STATUS=124
# This bounds a hung command without treating ordinary contention as failure.
readonly CLI_HELP_ATTEMPT_TIMEOUT_SECONDS=60
# A transient deadline gets two retries before the invocation is incomplete.
readonly CLI_HELP_MAX_ATTEMPTS=3

failed=0
incomplete_commands=()

run_cli_help() {
    local attempt=1
    local status

    while (( attempt <= CLI_HELP_MAX_ATTEMPTS )); do
        if timeout "${CLI_HELP_ATTEMPT_TIMEOUT_SECONDS}s" uv run --quiet python -m teleclaude.cli.telec "$@" -h >/dev/null 2>&1; then
            return 0
        else
            status=$?
        fi

        if (( status != TIMEOUT_KILL_STATUS )); then
            return "$status"
        fi

        ((attempt += 1))
    done

    return "$TIMEOUT_KILL_STATUS"
}

record_cli_help_result() {
    local status
    local command

    command="python -m teleclaude.cli.telec $* -h"
    if run_cli_help "$@"; then
        return
    else
        status=$?
    fi

    if (( status == TIMEOUT_KILL_STATUS )); then
        incomplete_commands+=("$command")
        return
    fi

    echo "FAIL: $command"
    failed=1
}

# Only test commands that have subcommands (where -h can break in child handlers).
# Top-level -h is handled uniformly in _handle_cli_command and doesn't need per-commit validation.
while IFS=: read -r cmd subs; do
    record_cli_help_result "$cmd"
    for sub in $subs; do
        record_cli_help_result "$cmd" "$sub"
    done
done < <(uv run --quiet python -c "
from teleclaude.cli.telec import CLI_SURFACE
for name, cmd in CLI_SURFACE.items():
    if not cmd.subcommands:
        continue
    subs = ' '.join(cmd.subcommands.keys())
    print(f'{name}:{subs}')
")

if [[ $failed -eq 1 ]]; then
    echo ""
    echo "CLI help (-h) must exit 0 for all commands and subcommands."
    exit 1
fi

if (( ${#incomplete_commands[@]} > 0 )); then
    echo ""
    for command in "${incomplete_commands[@]}"; do
        echo "INCOMPLETE: $command did not return a verdict within ${CLI_HELP_ATTEMPT_TIMEOUT_SECONDS}s after ${CLI_HELP_MAX_ATTEMPTS} attempts."
    done
    exit "$TIMEOUT_KILL_STATUS"
fi
