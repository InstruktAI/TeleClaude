"""CLI subcommand handlers for telec tool subcommands.

All commands call the daemon REST API via tool_api_call() and print JSON to stdout.
Errors go to stderr with exit code 1 (handled by tool_api_call).

Handler naming: handle_{group}_{subcommand} for grouped commands,
handle_{command} for top-level commands.
"""

from __future__ import annotations

from teleclaude.cli.tool_commands.infra import (
    handle_agents,
    handle_agents_availability,
    handle_agents_status,
    handle_channels,
    handle_channels_list,
    handle_channels_publish,
    handle_computers,
    handle_projects,
)
from teleclaude.cli.tool_commands.sessions import (
    handle_sessions,
    handle_sessions_end,
    handle_sessions_escalate,
    handle_sessions_file,
    handle_sessions_list,
    handle_sessions_restart,
    handle_sessions_result,
    handle_sessions_run,
    handle_sessions_send,
    handle_sessions_start,
    handle_sessions_tail,
    handle_sessions_unsubscribe,
    handle_sessions_widget,
)
from teleclaude.cli.tool_commands.todo import (
    handle_operations,
    handle_operations_get,
    handle_todo_create,
    handle_todo_integrate,
    handle_todo_mark_finalize_ready,
    handle_todo_mark_phase,
    handle_todo_prepare,
    handle_todo_set_deps,
    handle_todo_work,
)

__all__ = [
    "handle_agents",
    "handle_agents_availability",
    "handle_agents_status",
    "handle_channels",
    "handle_channels_list",
    "handle_channels_publish",
    # infra
    "handle_computers",
    "handle_operations",
    "handle_operations_get",
    "handle_projects",
    # sessions
    "handle_sessions",
    "handle_sessions_end",
    "handle_sessions_escalate",
    "handle_sessions_file",
    "handle_sessions_list",
    "handle_sessions_restart",
    "handle_sessions_result",
    "handle_sessions_run",
    "handle_sessions_send",
    "handle_sessions_start",
    "handle_sessions_tail",
    "handle_sessions_unsubscribe",
    "handle_sessions_widget",
    # todo + operations
    "handle_todo_create",
    "handle_todo_integrate",
    "handle_todo_mark_finalize_ready",
    "handle_todo_mark_phase",
    "handle_todo_prepare",
    "handle_todo_set_deps",
    "handle_todo_work",
]
