"""Shared config-section requirement validation.

One source of truth for "is an enabled config section actually configured" —
used by the daemon startup path (decide whether to start an adapter), the
config TUI (refuse to persist an enabled-but-incomplete section), and any
downstream consumer gating on a service/provider being usable. Keeping the rule
here means it cannot drift between surfaces.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def is_unresolved_placeholder(value: object) -> bool:
    """Return True when a config value is empty or an unresolved ``${VAR}``.

    Config secrets are shipped as ``${VAR}`` references into ``.env``; an
    unresolved reference (or an empty/None value) means the field is not
    actually filled in. Treating the literal ``${VAR}`` string as a real value
    is the bug this guards against.
    """
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        return not stripped or (stripped.startswith("${") and stripped.endswith("}"))
    return False


@dataclass(frozen=True)
class _RequiredField:
    """A required field and where it resolves from.

    ``config_attr`` is read off the config section first; if it is empty or an
    unresolved placeholder, ``env_var`` (if any) is consulted. ``label`` is the
    human-facing field name surfaced in the "not configured" message.
    """

    label: str
    config_attr: str | None
    env_var: str | None


# Per-section required fields, encoding each section's real resolution path
# (discord: config token or env; telegram & email: env-only; whatsapp: config or env).
_REQUIRED_FIELDS: dict[str, tuple[_RequiredField, ...]] = {
    "discord": (_RequiredField("token", "token", "DISCORD_BOT_TOKEN"),),
    "telegram": (_RequiredField("bot token", None, "TELEGRAM_BOT_TOKEN"),),
    "whatsapp": (
        _RequiredField("phone_number_id", "phone_number_id", "WHATSAPP_PHONE_NUMBER_ID"),
        _RequiredField("access_token", "access_token", "WHATSAPP_ACCESS_TOKEN"),
    ),
    "email": (
        _RequiredField("SMTP_USERNAME", None, "SMTP_USERNAME"),
        _RequiredField("SMTP_KEY", None, "SMTP_KEY"),
        _RequiredField("EMAIL_FROM", None, "EMAIL_FROM"),
    ),
}


def _resolve_field(cfg: object, spec: _RequiredField) -> str:
    """Resolve a required field to its effective value (config field, else env).

    ``cfg`` may be a parsed config object (startup) or a raw config-section dict
    (config TUI, pre-persist) — both are read through one path.
    """
    if spec.config_attr is not None:
        raw = cfg.get(spec.config_attr) if isinstance(cfg, dict) else getattr(cfg, spec.config_attr, None)
        if not is_unresolved_placeholder(raw):
            return str(raw).strip()
    if spec.env_var:
        return os.getenv(spec.env_var, "").strip()
    return ""


def missing_required_fields(section: str, cfg: object) -> list[str]:
    """Return the required field labels that are missing/unconfigured for a section.

    ``cfg`` is either a parsed config object or a raw config-section dict. An
    empty list means fully configured; sections with no requirements always
    return an empty list.
    """
    return [spec.label for spec in _REQUIRED_FIELDS.get(section, ()) if not _resolve_field(cfg, spec)]


def validated_sections() -> frozenset[str]:
    """Config sections that carry required-field requirements (callers gate on these)."""
    return frozenset(_REQUIRED_FIELDS)
