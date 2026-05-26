"""Provider guidance registry for configuration fields.

Guidance content is data, not code: it lives in the adjacent ``guidance.yml`` and
is loaded once at import. Each entry is keyed by config field path and may carry
an ``env_var`` that ties it to a ${ENV} secret, so the same guidance surfaces in
both the Env subtab (looked up by env var) and the reflected config tabs (looked
up by field key).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

_GUIDANCE_FILE = Path(__file__).parent / "guidance.yml"


@dataclass(frozen=True)
class FieldGuidance:
    """Guidance for a specific configuration field."""

    description: str
    steps: list[str] = field(default_factory=list)
    url: str | None = None
    format_example: str | None = None
    validation_hint: str | None = None


class GuidanceRegistry:
    """Registry of guidance for configuration fields, loaded from guidance.yml."""

    def __init__(self, source: Path = _GUIDANCE_FILE) -> None:
        self._registry: dict[str, FieldGuidance] = {}
        self._env_to_field: dict[str, str] = {}
        self._load(source)

    def _load(self, source: Path) -> None:
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        for field_path, entry in raw.items():
            env_var = entry.get("env_var")
            self._registry[field_path] = FieldGuidance(
                description=str(entry.get("description", "")),
                steps=[str(s) for s in entry.get("steps", [])],
                url=entry.get("url"),
                format_example=entry.get("format_example"),
                validation_hint=entry.get("validation_hint"),
            )
            if isinstance(env_var, str) and env_var:
                self._env_to_field[env_var] = field_path

    def get(self, field_path: str) -> FieldGuidance | None:
        """Retrieve guidance by config field path."""
        return self._registry.get(field_path)

    def get_for_env(self, env_var_name: str) -> FieldGuidance | None:
        """Retrieve guidance by env var name."""
        field_path = self._env_to_field.get(env_var_name)
        return self._registry.get(field_path) if field_path else None

    def get_for_field_key(self, field_key: str) -> FieldGuidance | None:
        """Retrieve guidance for a reflected field key (e.g. ``telegram.bot_token``).

        Reflected keys omit the ``adapters.`` prefix the registry uses, so both
        forms are tried.
        """
        return self._registry.get(field_key) or self._registry.get(f"adapters.{field_key}")


# Global instance — callers use its methods directly (get_for_env / get_for_field_key).
guidance_registry = GuidanceRegistry()
