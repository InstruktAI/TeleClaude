"""Command handlers for TeleClaude bot commands.

Re-exports all public names from submodules for backward compatibility.
"""

from ._agent import (
    handoff_agent,
    resume_agent,
    run_agent_command,
    select_handoff_successor,
    start_agent,
)
from ._keys import (
    arrow_key_command,
    backspace_command,
    cancel_command,
    ctrl_command,
    enter_command,
    escape_command,
    keys,
    kill_command,
    shift_tab_command,
    tab_command,
)
from ._message import (
    deliver_inbound,
    handle_file,
    handle_voice,
    notify_delivery_exhausted,
    process_message,
)
from ._projects import list_projects, list_projects_with_todos, list_todos
from ._restart import agent_restart
from ._session import (
    close_session,
    create_session,
    end_session,
    get_computer_info,
    get_session_data,
    list_sessions,
)
from ._session_identity import SessionCreationRefused, resolve_working_slug_from_subdir
from ._utils import (
    EndSessionHandlerResult,
    SessionDataPayload,
    StartPollingFunc,
    with_session,
)

__all__ = [
    # _utils
    "EndSessionHandlerResult",
    "SessionCreationRefused",
    "SessionDataPayload",
    "StartPollingFunc",
    # _agent
    "agent_restart",
    # _keys
    "arrow_key_command",
    "backspace_command",
    "cancel_command",
    # _session
    "close_session",
    "create_session",
    "ctrl_command",
    # _message
    "deliver_inbound",
    "end_session",
    "enter_command",
    "escape_command",
    "get_computer_info",
    "get_session_data",
    "handle_file",
    "handle_voice",
    "handoff_agent",
    "keys",
    "kill_command",
    "list_projects",
    "list_projects_with_todos",
    "list_sessions",
    "list_todos",
    "notify_delivery_exhausted",
    "process_message",
    "resolve_working_slug_from_subdir",
    "resume_agent",
    "run_agent_command",
    "select_handoff_successor",
    "shift_tab_command",
    "start_agent",
    "tab_command",
    "with_session",
]
