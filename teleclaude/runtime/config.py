"""One-shot runtime configuration seam.

Reads the deployment-time path env vars exactly once at module import and
stores them in a frozen ``RuntimeConfig`` instance. Runtime code reads those
values through ``get_runtime_config()``.

Test isolation: call ``set_runtime_config(RuntimeConfig(...))`` once in the
test session's conftest *before* importing any other teleclaude module. The
singleton is then fixed for the lifetime of the import. Per-test overrides use
``monkeypatch.setattr`` on this module's ``_instance``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_HOME = Path("~/.teleclaude").expanduser()


@dataclass(frozen=True)
class RuntimeConfig:
    home: Path = _DEFAULT_HOME
    config_path: Path | None = None
    env_path: Path | None = None
    project_config_path: Path | None = None
    tmpdir_base: Path | None = None


def _init_default() -> RuntimeConfig:
    raw_home = os.getenv("TELECLAUDE_HOME")
    home = Path(raw_home).expanduser() if raw_home else _DEFAULT_HOME

    raw_config = os.getenv("TELECLAUDE_CONFIG_PATH")
    config_path = Path(raw_config).expanduser() if raw_config else None

    raw_env = os.getenv("TELECLAUDE_ENV_PATH")
    env_path = Path(raw_env).expanduser() if raw_env else None

    raw_project_config = os.getenv("TELECLAUDE_PROJECT_CONFIG_PATH")
    project_config_path = Path(raw_project_config).expanduser() if raw_project_config else None

    raw_tmpdir = os.getenv("TELECLAUDE_SESSION_TMPDIR_BASE")
    tmpdir_base = Path(raw_tmpdir).expanduser() if raw_tmpdir else None

    return RuntimeConfig(
        home=home,
        config_path=config_path,
        env_path=env_path,
        project_config_path=project_config_path,
        tmpdir_base=tmpdir_base,
    )


_instance: RuntimeConfig = _init_default()


def get_runtime_config() -> RuntimeConfig:
    """Return the active RuntimeConfig singleton."""
    return _instance


def set_runtime_config(config: RuntimeConfig) -> None:
    """Replace the active RuntimeConfig singleton.

    Call once at process startup (or in test conftest) before importing
    modules that derive paths from it.  Not thread-safe after import time.
    """
    global _instance
    _instance = config
