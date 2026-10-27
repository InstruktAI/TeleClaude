"""Session-start context naming the shell an agent's commands run in.

Each agent CLI selects the shell for its command tool by its own rule; the
receiver inherits that CLI's environment, so it resolves the same shell the
CLI resolved and tells the agent how to write commands for it.
"""

from __future__ import annotations

import os
import pwd
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Final

from teleclaude.core.agents import AgentName


class CommandShell(StrEnum):
    """Shells whose command-writing guidance the receiver carries."""

    BASH = "bash"
    ZSH = "zsh"


_SHELL_ENV: Final = "SHELL"
_CLAUDE_SHELL_OVERRIDE_ENV: Final = "CLAUDE_CODE_SHELL"

_ZSH_CONTEXT: Final = (
    "Command shell: your shell commands run in zsh ({shell_path}), not bash. Write them for zsh:\n"
    "- Quote a pattern meant for a program (`rg -g '*.md'`, `find . -name '*.py'`): "
    "zsh aborts the whole command when an unquoted pattern matches no file.\n"
    "- Compare with `=` inside `[ ]`: zsh expands a word starting with `=` as a command path, "
    "so `==` and `echo ===` fail.\n"
    '- Hold a command and its arguments in an array (`cmd=(git log -1); "${{cmd[@]}}"`): '
    "zsh runs an unquoted string variable as one word.\n"
    "- Name variables something other than `path`, which zsh ties to PATH so assigning it replaces PATH, "
    "and `status`, which is read-only.\n"
    "- Run bash-only code with `bash -c '...'`. Check `bash --version` before relying on bash 4 or later, "
    "and `command -v` before relying on a tool or a GNU-only flag."
)
_BASH_CONTEXT: Final = (
    "Command shell: your shell commands run in bash ({shell_path}). "
    "Check `bash --version` before relying on bash 4 or later, "
    "and `command -v` before relying on a tool or a GNU-only flag."
)
_CONTEXT_BY_SHELL: Final[dict[CommandShell, str]] = {
    CommandShell.BASH: _BASH_CONTEXT,
    CommandShell.ZSH: _ZSH_CONTEXT,
}


def _shell_kind(shell_path: str | None) -> CommandShell | None:
    if not shell_path:
        return None
    try:
        return CommandShell(Path(shell_path).name)
    except ValueError:
        return None


def _account_login_shell() -> str | None:
    try:
        return pwd.getpwuid(os.getuid()).pw_shell
    except KeyError:
        return None


def _claude_command_shell() -> str | None:
    override = os.getenv(_CLAUDE_SHELL_OVERRIDE_ENV)  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
    shell = os.getenv(_SHELL_ENV)  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
    for candidate in (override, shell):
        if _shell_kind(candidate) is not None:
            return candidate
    return _account_login_shell()


_SHELL_RESOLVERS: Final[dict[AgentName, Callable[[], str | None]]] = {
    AgentName.CLAUDE: _claude_command_shell,
    AgentName.CODEX: _account_login_shell,
}


def command_shell_context(provider: str) -> str | None:
    """Return command-writing guidance for the provider's command shell, when it is known."""
    try:
        agent = AgentName.from_str(provider)
    except ValueError:
        return None
    resolver = _SHELL_RESOLVERS.get(agent)
    if resolver is None:
        return None
    shell_path = resolver()
    kind = _shell_kind(shell_path)
    if kind is None:
        return None
    return _CONTEXT_BY_SHELL[kind].format(shell_path=shell_path)
