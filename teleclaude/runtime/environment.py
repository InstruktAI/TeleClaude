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
_SHELL_ENV_CAPTURE_TIMEOUT_SECONDS = 5
_SHELL_CAPTURE_ENV_REMOVALS = ("ZDOTDIR", "BASH_ENV", "ENV", "TELECLAUDE_HOST_SHELL")
_PATH_ENV_NAME = "PATH"
_HOST_XDG_ENV_NAMES: tuple[str, ...] = ("XDG_DATA_HOME", "XDG_CACHE_HOME")
_CAPTURED_ENV_NAMES: tuple[str, ...] = (_PATH_ENV_NAME, *_HOST_XDG_ENV_NAMES)
_EMPTY_ENV_VALUE = ""
_ENV_ASSIGNMENT_SEPARATOR = "="
_SHELL_CAPTURE_SENTINEL = "__teleclaude_env_capture__"
_SHELL_CAPTURE_SCRIPT = "\n".join(
    (
        f"printf '%s\\n' {_SHELL_CAPTURE_SENTINEL}",
        *(f"printf '{name}=%s\\n' \"${{{name}:-}}\"" for name in _CAPTURED_ENV_NAMES),
    )
)
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
        "TELEC_TUI_IDENTITY",
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
    }
)


class RuntimeEnvironment(TypedDict):
    """Environment values resolved at tmux session creation time."""

    PATH: str
    SHELL: NotRequired[str]
    XDG_DATA_HOME: NotRequired[str]
    XDG_CACHE_HOME: NotRequired[str]


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
    source = env if env is not None else os.environ  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state

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


def _capture_shell_environment(shell_value: str, env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Capture the environment values declared by the user's login shell.

    A subprocess is required here: only the user's own shell evaluates the rc
    files that declare these values, and no Python API reproduces that
    evaluation.
    """
    try:
        result = subprocess.run(
            [shell_value, "-lic", _SHELL_CAPTURE_SCRIPT],
            env=_host_shell_capture_env(env),
            capture_output=True,
            text=True,
            timeout=_SHELL_ENV_CAPTURE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("failed to capture environment from user shell: shell=%s error=%s", shell_value, exc)
        return {}

    if result.returncode != 0:
        logger.warning(
            "user shell environment capture failed; falling back to daemon environment: "
            "shell=%s returncode=%s stderr=%s",
            shell_value,
            result.returncode,
            result.stderr.strip(),
        )
        return {}

    sentinel_index = result.stdout.find(_SHELL_CAPTURE_SENTINEL)
    if sentinel_index < 0:
        logger.warning(
            "user shell environment capture produced no sentinel marker; falling back to daemon environment: "
            "shell=%s stdout=%s",
            shell_value,
            result.stdout.strip(),
        )
        return {}

    captured: dict[str, str] = {}
    block = result.stdout[sentinel_index + len(_SHELL_CAPTURE_SENTINEL) :]
    for line in block.splitlines():
        name, separator, value = line.partition(_ENV_ASSIGNMENT_SEPARATOR)
        if not separator or name not in _CAPTURED_ENV_NAMES or name in captured:
            continue
        if value:
            captured[name] = value

    if _PATH_ENV_NAME not in captured:
        logger.warning(
            "user shell environment capture declared no PATH; falling back to daemon environment: shell=%s",
            shell_value,
        )
    return captured


def host_xdg_env(runtime_env: RuntimeEnvironment) -> dict[str, str]:
    """Return the XDG base dirs a resolved runtime environment carries."""
    values: dict[str, str] = {}
    data_home = runtime_env.get("XDG_DATA_HOME")
    if data_home is not None:
        values["XDG_DATA_HOME"] = data_home
    cache_home = runtime_env.get("XDG_CACHE_HOME")
    if cache_home is not None:
        values["XDG_CACHE_HOME"] = cache_home
    return values


def resolve_runtime_environment(env: Mapping[str, str] | None = None) -> RuntimeEnvironment:
    """Resolve the live session environment from the daemon and configured user shell.

    A name the user shell does not declare falls back to the daemon process
    environment's value for that name.
    """
    source = env if env is not None else os.environ  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
    user_shell = resolve_user_shell(source)
    captured = _capture_shell_environment(user_shell, source) if user_shell else {}
    path_value = captured.get(_PATH_ENV_NAME) or source.get(_PATH_ENV_NAME, _EMPTY_ENV_VALUE)
    values: RuntimeEnvironment = {"PATH": compose_runtime_path(path_value)}
    if user_shell:
        values["SHELL"] = user_shell
    data_home = captured.get("XDG_DATA_HOME") or source.get("XDG_DATA_HOME", _EMPTY_ENV_VALUE)
    if data_home:
        values["XDG_DATA_HOME"] = data_home
    cache_home = captured.get("XDG_CACHE_HOME") or source.get("XDG_CACHE_HOME", _EMPTY_ENV_VALUE)
    if cache_home:
        values["XDG_CACHE_HOME"] = cache_home
    return values
