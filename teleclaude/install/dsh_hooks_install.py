"""DeepSeek Harness receiver-hooks configuration."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

HOOKS_KEY = "hooks"

# dsh-TUI keeps its first-run guide state in its own per-machine data directory.
# The guide is recorded as done only when completed, never when skipped, so an
# unrecorded machine is offered it on every launch and the composer is not
# reachable until it is dismissed. The record shape and revision are owned by
# the dsh-TUI package (its onboarding preferences module).
DSH_TUI_DATA_DIRNAME = ".dsh-tui"
DSH_TUI_ONBOARDING_FILENAME = "onboarding.json"
DSH_TUI_ONBOARDING_VERSION = 1
_ONBOARDING_COMPLETED_KEY = "completed"
_ONBOARDING_VERSION_KEY = "version"
_ONBOARDING_RECORD: dict[str, bool | int] = {
    _ONBOARDING_COMPLETED_KEY: True,
    _ONBOARDING_VERSION_KEY: DSH_TUI_ONBOARDING_VERSION,
}
_ONBOARDING_FILE_TERMINATOR = "\n"
_ONBOARDING_RECORDED_MESSAGE = "DeepSeek TUI first-run guide recorded as complete in {path}"
HookMerger = Callable[  # guard: loose-dict - hooks.json is a dynamic external wire shape
    [dict[str, Any], dict[str, Any]], dict[str, Any]
]
HookPruner = Callable[  # guard: loose-dict - hooks.json is a dynamic external wire shape
    [dict[str, Any], set[str]], dict[str, Any]
]


# guard: loose-dict-func - hooks.json is a dynamic external wire shape
def configure_dsh(
    *,
    hooks_map: dict[str, Any],
    merge_hook_maps: HookMerger,
    prune_hook_maps: HookPruner,
) -> None:
    """Write TeleClaude receiver hooks into the global DSH hooks layer.

    Writes the global ~/.dsh/hooks.json (respecting $DSH_HOME) in the nested
    Claude Code settings shape, merging idempotently with any existing user
    hooks (dedup by receiver script path, matching merge_hooks semantics).

    Plugin installation and activation remain package-owned: the dsh-hooks
    package declares its own ``dsh.bundle.patch`` and the DSH installer composes
    that patch when the package is added to a profile.
    """
    dsh_home = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
    hooks_path = dsh_home / "hooks.json"
    hooks_path.parent.mkdir(parents=True, exist_ok=True)

    settings = _load_dsh_settings(hooks_path)
    if settings is None:
        return

    # Accept both the nested CC shape ({"hooks": {...}}) and a flat event map.
    existing_hooks = settings.get(HOOKS_KEY, settings)
    if not isinstance(existing_hooks, dict):
        existing_hooks = {}
    pruned_hooks = prune_hook_maps(existing_hooks, set(hooks_map))
    merged_hooks = merge_hook_maps(pruned_hooks, hooks_map)

    out_settings = dict(settings)
    out_settings[HOOKS_KEY] = merged_hooks
    out_settings.setdefault("$schema", "https://json.schemastore.org/claude-code-settings.json")

    hooks_path.write_text(json.dumps(out_settings, indent=2) + "\n")
    print(f"DeepSeek Harness hooks configured in {hooks_path}")


def configure_dsh_tui_onboarding() -> None:
    """Record dsh-TUI's first-run guide as complete so launches reach the composer.

    A record that already marks the guide complete at this revision or later is
    left untouched; anything else (absent, unreadable, incomplete, older) is
    replaced, matching how dsh-TUI itself reads such a file as "not done yet".
    """
    onboarding_path = Path.home() / DSH_TUI_DATA_DIRNAME / DSH_TUI_ONBOARDING_FILENAME
    if _onboarding_recorded(onboarding_path):
        return
    onboarding_path.parent.mkdir(parents=True, exist_ok=True)
    onboarding_path.write_text(json.dumps(_ONBOARDING_RECORD, indent=2) + _ONBOARDING_FILE_TERMINATOR)
    print(_ONBOARDING_RECORDED_MESSAGE.format(path=onboarding_path))


def _onboarding_recorded(path: Path) -> bool:
    """Whether the file already records the guide complete at this revision or later."""
    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(record, dict):
        return False
    version = record.get(_ONBOARDING_VERSION_KEY)
    return (
        record.get(_ONBOARDING_COMPLETED_KEY) is True
        and isinstance(version, int)
        and not isinstance(version, bool)
        and version >= DSH_TUI_ONBOARDING_VERSION
    )


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
