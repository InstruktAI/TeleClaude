"""The machine runtime environment: the process environment with the checkout's ``.env`` applied.

Every resolution of the machine configuration's ``${NAME}`` references reads this one environment,
so the daemon, ``telec config validate``, the configuration writers and installation all see the
same values.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from teleclaude.config._environment import read_environment_file
from teleclaude.paths import PROJECT_ENV_PATH

# Variables present before any .env load are shell-provided and keep precedence;
# .env-sourced variables are refreshed from the file on every read of the environment.
_PRE_DOTENV_ENV_KEYS = frozenset(os.environ)
# Keys currently sourced from .env, so a refresh can drop ones deleted from the file.
_dotenv_managed_keys: set[str] = set()


def machine_runtime_environment() -> Mapping[str, str]:
    """Return the process environment with the checkout's ``.env`` freshly applied.

    Shell-provided variables (captured before the first application) keep precedence over
    ``.env``. ``.env``-sourced variables are refreshed on each call, and ones removed from the
    file are dropped, so a reload reflects both edits and deletions of the ``${NAME}``-backed
    values the TUI writes to ``.env``.
    """
    values = read_environment_file(PROJECT_ENV_PATH)
    current = {key for key in values if key not in _PRE_DOTENV_ENV_KEYS}
    for key in _dotenv_managed_keys - current:
        os.environ.pop(key, None)
    for key in current:
        os.environ[key] = values[key]
    _dotenv_managed_keys.clear()
    _dotenv_managed_keys.update(current)
    return os.environ
