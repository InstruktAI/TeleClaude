"""Command handlers for TeleClaude bot commands.

Re-exports all public names from submodules for backward compatibility.
"""

from ._agent import (
    agent_restart,
    resume_agent,
    run_agent_command,
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
    process_message,
)
from ._session import (
    close_session,
    create_session,
    end_session,
    get_computer_info,
    get_session_data,
    list_projects,
    list_projects_with_todos,
    list_sessions,
    list_todos,
)
from ._utils import (
    EndSessionHandlerResult,
    SessionDataPayload,
    StartPollingFunc,
    with_session,
)

__all__ = [
    # _utils
    "EndSessionHandlerResult",
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
    "keys",
    "kill_command",
    "list_projects",
    "list_projects_with_todos",
    "list_sessions",
    "list_todos",
    "process_message",
    "resume_agent",
    "run_agent_command",
    "shift_tab_command",
    "start_agent",
    "tab_command",
    "with_session",
]
