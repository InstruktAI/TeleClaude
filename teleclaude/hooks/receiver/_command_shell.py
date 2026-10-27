"""Session-start context for agents running on a zsh host shell."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from teleclaude.runtime.environment import resolve_user_shell

_ZSH_SHELL_NAME: Final = "zsh"
_ZSH_CONTEXT: Final = (
    "Command shell: this host's shell is zsh ({shell_path}), not bash. Write commands for zsh:\n"
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


def host_shell_context() -> str | None:
    """Return zsh command-writing guidance when the host shell is zsh."""
    shell_path = resolve_user_shell()
    if shell_path is None or Path(shell_path).name != _ZSH_SHELL_NAME:
        return None
    return _ZSH_CONTEXT.format(shell_path=shell_path)
