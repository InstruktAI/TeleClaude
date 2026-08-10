"""One-shot runtime configuration seam.

Reads the deployment-time ``TELECLAUDE_HOME`` env var exactly once at module
import and stores it in a frozen ``RuntimeConfig`` instance. Runtime code
reads that value through ``get_runtime_config()``.

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


def _init_default() -> RuntimeConfig:
    raw_home = os.getenv("TELECLAUDE_HOME")
    home = Path(raw_home).expanduser() if raw_home else _DEFAULT_HOME

    return RuntimeConfig(home=home)


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
