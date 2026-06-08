"""Runtime config bootstrap: seed the machine-local config from the bundled template."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import yaml

from teleclaude.runtime.config import get_runtime_config

DeepMerge = Callable[[dict[str, object], dict[str, object]], dict[str, object]]  # guard: loose-dict - YAML config merge


def resolve_runtime_config_path(blueprint_path: Path, deep_merge: DeepMerge) -> Path:
    """Return the runtime config path, seeding/merging from the blueprint.

    The bundled ``templates/config.yml`` is a read-only blueprint
    (sane defaults + ${VAR} placeholders). The machine-local ``~/.teleclaude/config.yml``
    is the only file the TUI/daemon read and write: it is seeded from the blueprint on
    first run, and any blueprint keys missing from the runtime are merged in (runtime
    values win; placeholders preserved). The blueprint itself is never written.

    An explicit ``config_path`` in RuntimeConfig is used verbatim and bypasses seeding.
    """
    rc = get_runtime_config()
    if rc.config_path is not None:
        return rc.config_path.expanduser().resolve()

    runtime = rc.home / "config.yml"
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
