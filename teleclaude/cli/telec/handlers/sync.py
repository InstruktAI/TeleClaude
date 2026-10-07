"""Run the invocation root's maintenance on demand, or list the steps a run would perform."""

from __future__ import annotations

import sys

from teleclaude.cli.telec.flags import FLAG_SYNC_LIST
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import SYNC
from teleclaude.core.integration.on_demand_maintenance import list_on_demand, run_on_demand
from teleclaude.project_root import resolve_invocation_roots

__all__ = ["handle_sync"]

_SYNC_POSITIONALS_REFUSED = "telec sync accepts no positional arguments."
_USAGE_EXIT_CODE = 2


def _print_line(line: str) -> None:
    """Print one report line at once, so it stays in order beside the steps' own output."""
    print(line, flush=True)


def handle_sync(args: list[str]) -> None:
    """Perform the maintenance steps of the invocation directory's root, or list them with ``--list``."""
    parsed = parse_command_args(SYNC, args)
    if parsed.positionals:
        print(_SYNC_POSITIONALS_REFUSED, file=sys.stderr)
        raise SystemExit(_USAGE_EXIT_CODE)

    invocation_directory = resolve_invocation_roots().invocation_dir
    if parsed.has(FLAG_SYNC_LIST):
        listing = list_on_demand(invocation_directory, _print_line)
        if listing.refusal is not None:
            print(listing.refusal, file=sys.stderr)
        if listing.exit_code:
            raise SystemExit(listing.exit_code)
        return
    result = run_on_demand(invocation_directory, _print_line)
    if result.refusal is not None:
        print(result.refusal, file=sys.stderr)
    if result.exit_code:
        raise SystemExit(result.exit_code)
