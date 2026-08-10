"""Runtime environment contract for managed agent sessions."""

from __future__ import annotations

import os
import pwd
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import NotRequired, TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.paths import BIN_DIR

logger = get_logger(__name__)
_SHELL_PATH_CAPTURE_TIMEOUT_SECONDS = 5
_SHELL_CAPTURE_ENV_REMOVALS = ("ZDOTDIR", "BASH_ENV", "ENV", "TELECLAUDE_HOST_SHELL")
_TMUX_RUNTIME_ENV_EXACT_ALLOWLIST = frozenset(
    {
        "APPEARANCE_MODE",
        "LANG",
        "LC_ALL",
        "LC_COLLATE",
        "LC_CTYPE",
        "LC_MESSAGES",
        "LC_MONETARY",
        "LC_NUMERIC",
        "LC_TIME",
        "TERMINAL_BG",
    }
)
_TUI_ENV_EXTRA_ALLOWLIST = frozenset(
    {
        "COLORTERM",
        "HOME",
        "LOGNAME",
        "NO_COLOR",
        "PATH",
        "PWD",
        "REAL_TERM_PROGRAM",
        "TELEC_INVOCATION_CWD",
        "TELEC_RELOAD",
        "TELEC_TUI_SESSION",
        "TELECLAUDE_HOME",
        "TEMP",
        "TERM",
        "TERM_PROGRAM",
        "TERM_PROGRAM_VERSION",
        "TMP",
        "TMPDIR",
        "USER",
        "UV_NO_SYNC",
    }
)
_PLATFORM_SESSION_ENV_EXTRA_ALLOWLIST = frozenset(
    {
        "ELEVENLABS_VOICE_ID",
        "MACOS_VOICE",
        "OPENAI_VOICE",
        "TELECLAUDE_LOG_LEVEL",
    }
)


class RuntimeEnvironment(TypedDict):
    """Environment values resolved at tmux session creation time."""

    PATH: str
    SHELL: NotRequired[str]


def _filter_tmux_environment(env: Mapping[str, str], extra_allowlist: Iterable[str] = ()) -> dict[str, str]:
    allowlist = _TMUX_RUNTIME_ENV_EXACT_ALLOWLIST | frozenset(extra_allowlist)
    return {key: value for key, value in env.items() if key in allowlist}


def filter_tmux_runtime_environment(env: Mapping[str, str]) -> dict[str, str]:
    """Return non-secret runtime env vars common to TeleClaude tmux sessions."""

    return _filter_tmux_environment(env)


def filter_tui_tmux_environment(env: Mapping[str, str]) -> dict[str, str]:
    """Return the narrow environment allowed through tmux ``-e`` for the TUI."""

    return _filter_tmux_environment(env, _TUI_ENV_EXTRA_ALLOWLIST)


def filter_platform_session_environment(env: Mapping[str, str]) -> dict[str, str]:
    """Return TeleClaude-owned session env vars allowed beside project config."""

    return _filter_tmux_environment(env, _PLATFORM_SESSION_ENV_EXTRA_ALLOWLIST)


def _dedupe_path_entries(entries: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for entry in entries:
        if not entry or entry in seen:
            continue
        seen.add(entry)
        deduped.append(entry)
    return deduped


def compose_runtime_path(path_value: str, *, teleclaude_bin: Path = BIN_DIR) -> str:
    """Return PATH with TeleClaude bin first and all existing entries preserved."""
    entries = [str(teleclaude_bin), *path_value.split(os.pathsep)]
    return os.pathsep.join(_dedupe_path_entries(entries))


def _is_teleclaude_shell(shell_value: str) -> bool:
    return Path(shell_value.strip()).name == "teleclaude-shell"


def _account_shell() -> str | None:
    try:
        shell_value = pwd.getpwuid(os.getuid()).pw_shell.strip()
    except (KeyError, OSError):
        return None
    return shell_value or None


def resolve_user_shell(env: Mapping[str, str] | None = None) -> str | None:
    """Resolve the user's configured shell without assuming a shell path."""
    source = env if env is not None else os.environ

    shell_value = source.get("SHELL", "").strip()
    if shell_value and not _is_teleclaude_shell(shell_value):
        return shell_value

    account_shell = _account_shell()
    if account_shell and not _is_teleclaude_shell(account_shell):
        return account_shell
    return None


def _host_shell_capture_env(env: Mapping[str, str] | None) -> dict[str, str] | None:
    if env is None:
        return None
    cleaned = dict(env)
    for key in _SHELL_CAPTURE_ENV_REMOVALS:
        cleaned.pop(key, None)
    return cleaned


def _capture_path_from_shell(shell_value: str, env: Mapping[str, str] | None = None) -> str | None:
    try:
        result = subprocess.run(
            [shell_value, "-lic", 'printf %s "$PATH"'],
            env=_host_shell_capture_env(env),
            capture_output=True,
            text=True,
            timeout=_SHELL_PATH_CAPTURE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("failed to capture PATH from user shell: shell=%s error=%s", shell_value, exc)
        return None

    captured_path = result.stdout.strip()
    if result.returncode == 0 and captured_path:
        return captured_path

    logger.warning(
        "user shell PATH capture failed; falling back to daemon environment: shell=%s returncode=%s stderr=%s",
        shell_value,
        result.returncode,
        result.stderr.strip(),
    )
    return None


def resolve_runtime_environment(env: Mapping[str, str] | None = None) -> RuntimeEnvironment:
    """Resolve the live session environment from the daemon and configured user shell."""
    source = env if env is not None else os.environ
    user_shell = resolve_user_shell(source)
    captured_path = _capture_path_from_shell(user_shell, source) if user_shell else None
    path_value = captured_path or source.get("PATH", "")
    resolved: RuntimeEnvironment = {"PATH": compose_runtime_path(path_value)}
    if user_shell:
        resolved["SHELL"] = user_shell
    return resolved
