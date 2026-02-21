#!/usr/bin/env bash
# Verify all CLI commands and subcommands respond to -h without error.
# Triggered by pre-commit when CLI modules are touched.

set -euo pipefail

failed=0

# Only test commands that have subcommands (where -h can break in child handlers).
# Top-level -h is handled uniformly in _handle_cli_command and doesn't need per-commit validation.
while IFS=: read -r cmd subs; do
    if ! timeout 5 telec "$cmd" -h >/dev/null 2>&1; then
        echo "FAIL: telec $cmd -h"
        failed=1
    fi
    for sub in $subs; do
        if ! timeout 5 telec "$cmd" "$sub" -h >/dev/null 2>&1; then
            echo "FAIL: telec $cmd $sub -h"
            failed=1
        fi
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
