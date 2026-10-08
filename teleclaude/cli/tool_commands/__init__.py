"""CLI subcommand handlers for telec tool subcommands.

All commands call the daemon REST API via tool_api_call() and print JSON to stdout.
Errors go to stderr with exit code 1 (handled by tool_api_call).

Each submodule holds one command family and is imported only by the command that
selects it; this package re-exports nothing.

Handler naming: handle_{group}_{subcommand} for grouped commands,
handle_{command} for top-level commands.
"""
