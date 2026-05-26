"""Runtime config bootstrap: seed the machine-local config from the repo blueprint."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import yaml

from teleclaude.paths import TELECLAUDE_HOME

DeepMerge = Callable[[dict[str, object], dict[str, object]], dict[str, object]]  # guard: loose-dict - YAML config merge


def resolve_runtime_config_path(blueprint_path: Path, deep_merge: DeepMerge) -> Path:
    """Return the runtime config path, seeding/merging from the blueprint.

    The repo ``config.yml`` is a read-only blueprint (sane defaults + ${VAR}
    placeholders). The machine-local ``~/.teleclaude/config.yml`` is the only file
    the TUI/daemon read and write: it is seeded from the blueprint on first run,
    and any blueprint keys missing from the runtime are merged in (runtime values
    win; placeholders preserved). The blueprint itself is never written.

    An explicit ``TELECLAUDE_CONFIG_PATH`` (tests, alternate configs) is used
    verbatim and bypasses seeding.
    """
    env_path = os.getenv("TELECLAUDE_CONFIG_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    runtime = TELECLAUDE_HOME / "config.yml"
    if not blueprint_path.exists():
        return runtime

    runtime.parent.mkdir(parents=True, exist_ok=True)
    blueprint_raw = yaml.safe_load(blueprint_path.read_text(encoding="utf-8")) or {}
    runtime_raw: object = {}
    if runtime.exists():
        runtime_raw = yaml.safe_load(runtime.read_text(encoding="utf-8")) or {}

    if isinstance(blueprint_raw, dict) and isinstance(runtime_raw, dict):
        seeded = deep_merge(blueprint_raw, runtime_raw)  # runtime wins; blueprint fills gaps
        if seeded != runtime_raw:
            runtime.write_text(yaml.safe_dump(seeded, sort_keys=False), encoding="utf-8")
    return runtime
