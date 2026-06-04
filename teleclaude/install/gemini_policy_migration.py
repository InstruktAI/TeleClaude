"""Gemini Policy Engine deployment helpers."""

from __future__ import annotations

import json
from pathlib import Path

type JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
type JsonObject = dict[str, JsonValue]

GEMINI_TOOLS_KEY = "tools"
GEMINI_LEGACY_ALLOWED_KEY = "allowed"
GEMINI_POLICY_SOURCE_FILENAME = "gemini-policy.toml"
GEMINI_POLICY_TARGET_FILENAME = "teleclaude.toml"


def without_legacy_tools_allowed(settings: JsonObject) -> tuple[JsonObject, bool]:
    tools_value = settings.get(GEMINI_TOOLS_KEY)
    if not isinstance(tools_value, dict) or GEMINI_LEGACY_ALLOWED_KEY not in tools_value:
        return settings, False

    tools = dict(tools_value)
    del tools[GEMINI_LEGACY_ALLOWED_KEY]
    updated = dict(settings)
    updated[GEMINI_TOOLS_KEY] = tools
    return updated, True


def delete_legacy_tools_allowed(settings_path: Path) -> bool:
    if not settings_path.exists():
        return False

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        return False

    updated, changed = without_legacy_tools_allowed(settings)
    if changed:
        settings_path.write_text(json.dumps(updated, indent=2), encoding="utf-8")
    return changed


def deploy_policy_file(*, source_dir: Path, gemini_home: Path) -> Path:
    source = source_dir / GEMINI_POLICY_SOURCE_FILENAME
    target = gemini_home / "policies" / GEMINI_POLICY_TARGET_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target
