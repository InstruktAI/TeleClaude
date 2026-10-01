"""The launch profile a session's agent runs under, rendered for one launch.

Every path that launches, resumes, restores or hands off a session's agent
asks this module, so a session confined at a help desk is never launched
under another profile.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from teleclaude.agent_registry import AgentName, LaunchProfile
from teleclaude.caller_identity import is_desk_role
from teleclaude.constants import HUMAN_ROLE_ADMIN
from teleclaude.core.identity import session_person_role
from teleclaude.core.models import Session
from teleclaude.core.session_utils import get_session_output_dir, resolve_working_dir
from teleclaude.core.tool_access import desk_command_paths
from teleclaude.install.configure_agent_cli import claude_platform_hooks
from teleclaude.paths import REPO_ROOT

_CLAUDE_HOOKS_KEY = "hooks"
_DESK_INSTRUCTIONS_FILE = "AGENTS.md"
_DESK_BASH_RULE_TEMPLATE = "Bash(telec {path} *)"
_DESK_SETTINGS_FLAG = "--settings"
_DESK_ADD_DIR_FLAG = "--add-dir"
_DESK_APPEND_PROMPT_FILE_FLAG = "--append-system-prompt-file"
_NO_DESK_RENDERER_TEMPLATE = "Agent '{agent}' has no help-desk launch rendering"
_FLAG_SEPARATOR = " "

# Launch settings for a Claude desk session. The desk profile loads no user,
# project or local settings source, so these are the session's whole
# permission set: don't-ask mode denies every tool call that is not
# pre-approved here, the read fence keeps the file tools inside the working
# directories, only managed instructions load at startup, and memory and web
# tools stay off. The allow list and TeleClaude's own hooks are added per
# launch; no other hook source loads, so no hook can approve a call.
_CLAUDE_DESK_SETTINGS: dict[str, object] = {  # guard: loose-dict - vendor settings document
    "forceLoginMethod": "claudeai",
    "enabledMcpjsonServers": [],
    "autoMemoryEnabled": False,
    "pluginConfigs": {"agents-md@builtin": {"options": {"instructionFiles": "managed-only"}}},
}
_CLAUDE_DESK_PERMISSIONS: dict[str, object] = {  # guard: loose-dict - vendor settings document
    "defaultMode": "dontAsk",
    "blockReadsOutsideWorkingDirectories": True,
    "deny": ["WebFetch", "WebSearch"],
}
_PERMISSIONS_KEY = "permissions"
_ALLOW_KEY = "allow"


@dataclass(frozen=True)
class SessionLaunchProfile:
    """A launch profile name plus the flags rendered for this one launch."""

    profile: LaunchProfile
    flags: str = ""


def _render_claude_desk_flags(session: Session) -> str:
    allow = [_DESK_BASH_RULE_TEMPLATE.format(path=path) for path in desk_command_paths(session.human_role)]
    settings = {
        **_CLAUDE_DESK_SETTINGS,
        _PERMISSIONS_KEY: {**_CLAUDE_DESK_PERMISSIONS, _ALLOW_KEY: allow},
        _CLAUDE_HOOKS_KEY: claude_platform_hooks(REPO_ROOT),
    }
    parts = [
        _DESK_SETTINGS_FLAG,
        shlex.quote(json.dumps(settings)),
        _DESK_ADD_DIR_FLAG,
        # The upload helper's root is relative to the daemon's working
        # directory; the agent runs in its desk folder, so it gets the
        # resolved host-side path.
        shlex.quote(str(get_session_output_dir(session.session_id).resolve())),
    ]
    desk_instructions = Path(resolve_working_dir(session.project_path, session.subdir)) / _DESK_INSTRUCTIONS_FILE
    if desk_instructions.is_file():
        parts.extend((_DESK_APPEND_PROMPT_FILE_FLAG, shlex.quote(str(desk_instructions))))
    return _FLAG_SEPARATOR.join(parts)


# Agents with a verified desk confinement (`AgentDefinition.desk_confinement`)
# and how their per-launch desk flags are rendered.
_DESK_RENDERERS: dict[AgentName, Callable[[Session], str]] = {
    AgentName.CLAUDE: _render_claude_desk_flags,
}


def resolve_session_launch_profile(session: Session, agent: str) -> SessionLaunchProfile:
    """Choose the launch profile for a session's agent and render its per-launch flags.

    A session placed at a help desk runs under the desk profile; an admin's
    session under the default profile; every other session under the
    restricted profile. An agent without a desk rendering cannot launch a desk
    session.
    """
    if is_desk_role(session.system_role, session.human_role):
        renderer = _DESK_RENDERERS.get(AgentName.from_str(agent))
        if renderer is None:
            raise ValueError(_NO_DESK_RENDERER_TEMPLATE.format(agent=agent))
        return SessionLaunchProfile(LaunchProfile.HELP_DESK, renderer(session))
    if session_person_role(session) == HUMAN_ROLE_ADMIN:
        return SessionLaunchProfile(LaunchProfile.DEFAULT)
    return SessionLaunchProfile(LaunchProfile.RESTRICTED)
