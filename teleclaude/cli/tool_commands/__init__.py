"""CLI subcommand handlers for telec tool subcommands.

All commands call the daemon REST API via tool_api_call() and print JSON to stdout.
Errors go to stderr with exit code 1 (handled by tool_api_call).

Handler naming: handle_{group}_{subcommand} for grouped commands,
handle_{command} for top-level commands.
"""

from __future__ import annotations

from teleclaude.cli.tool_commands import infra as _infra
from teleclaude.cli.tool_commands import sessions as _sessions
from teleclaude.cli.tool_commands import todo as _todo

handle_agents = _infra.handle_agents
handle_agents_availability = _infra.handle_agents_availability
handle_agents_status = _infra.handle_agents_status
handle_channels = _infra.handle_channels
handle_channels_list = _infra.handle_channels_list
handle_channels_publish = _infra.handle_channels_publish
handle_computers = _infra.handle_computers
handle_projects = _infra.handle_projects

handle_sessions = _sessions.handle_sessions
handle_sessions_end = _sessions.handle_sessions_end
handle_sessions_escalate = _sessions.handle_sessions_escalate
handle_sessions_file = _sessions.handle_sessions_file
handle_sessions_list = _sessions.handle_sessions_list
handle_sessions_restart = _sessions.handle_sessions_restart
handle_sessions_result = _sessions.handle_sessions_result
handle_sessions_run = _sessions.handle_sessions_run
handle_sessions_send = _sessions.handle_sessions_send
handle_sessions_start = _sessions.handle_sessions_start
handle_sessions_tail = _sessions.handle_sessions_tail
handle_sessions_unsubscribe = _sessions.handle_sessions_unsubscribe
handle_sessions_widget = _sessions.handle_sessions_widget

handle_operations = _todo.handle_operations
handle_operations_get = _todo.handle_operations_get
handle_todo_create = _todo.handle_todo_create
handle_todo_integrate = _todo.handle_todo_integrate
handle_todo_mark_finalize_ready = _todo.handle_todo_mark_finalize_ready
handle_todo_mark_phase = _todo.handle_todo_mark_phase
handle_todo_prepare = _todo.handle_todo_prepare
handle_todo_set_deps = _todo.handle_todo_set_deps
handle_todo_work = _todo.handle_todo_work

__all__ = [
    "handle_agents",
    "handle_agents_availability",
    "handle_agents_status",
    "handle_channels",
    "handle_channels_list",
    "handle_channels_publish",
    "handle_computers",
    "handle_operations",
    "handle_operations_get",
    "handle_projects",
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
    "handle_todo_create",
    "handle_todo_integrate",
    "handle_todo_mark_finalize_ready",
    "handle_todo_mark_phase",
    "handle_todo_prepare",
    "handle_todo_set_deps",
    "handle_todo_work",
]
