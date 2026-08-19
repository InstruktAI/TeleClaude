"""DeepSeek Harness receiver-hooks configuration."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

HOOKS_KEY = "hooks"
HookMerger = Callable[  # guard: loose-dict - hooks.json is a dynamic external wire shape
    [dict[str, Any], dict[str, Any]], dict[str, Any]
]


# guard: loose-dict-func - hooks.json is a dynamic external wire shape
def configure_dsh(*, hooks_map: dict[str, Any], merge_hook_maps: HookMerger) -> None:
    """Write TeleClaude receiver hooks into the global DSH hooks layer.

    Writes the global ~/.dsh/hooks.json (respecting $DSH_HOME) in the nested
    Claude Code settings shape, merging idempotently with any existing user
    hooks (dedup by receiver script path, matching merge_hooks semantics).

    Plugin installation and activation remain package-owned: the dsh-hooks
    package declares its own ``dsh.bundle.patch`` and the DSH installer composes
    that patch when the package is added to a profile.
    """
    dsh_home = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
    hooks_path = dsh_home / "hooks.json"
    hooks_path.parent.mkdir(parents=True, exist_ok=True)

    settings = _load_dsh_settings(hooks_path)
    if settings is None:
        return

    # Accept both the nested CC shape ({"hooks": {...}}) and a flat event map.
    existing_hooks = settings.get(HOOKS_KEY, settings)
    if not isinstance(existing_hooks, dict):
        existing_hooks = {}
    merged_hooks = merge_hook_maps(existing_hooks, hooks_map)

    out_settings = dict(settings)
    out_settings[HOOKS_KEY] = merged_hooks
    out_settings.setdefault("$schema", "https://json.schemastore.org/claude-code-settings.json")

    hooks_path.write_text(json.dumps(out_settings, indent=2) + "\n")
    print(f"DeepSeek Harness hooks configured in {hooks_path}")


# guard: loose-dict-func - hooks.json is a dynamic external wire shape
def _load_dsh_settings(path: Path) -> dict[str, object] | None:
    """Load global DSH hook settings without importing the parent configurator."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        print(f"Warning: Failed to load DeepSeek Harness settings (invalid JSON): {exc}")
        return None
