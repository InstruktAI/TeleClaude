"""Shared config-section requirement validation.

One source of truth for "is an enabled config section actually configured" —
used by the daemon startup path (decide whether to start an adapter), the
config TUI (refuse to persist an enabled-but-incomplete section), and any
downstream consumer gating on a service/provider being usable. Keeping the rule
here means it cannot drift between surfaces.
"""

from __future__ import annotations

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
    """A required typed field and its human-facing validation label."""

    label: str
    config_attr: str


# Per-section required fields, read only from the typed config aggregate.
_REQUIRED_FIELDS: dict[str, tuple[_RequiredField, ...]] = {
    "discord": (_RequiredField("token", "token"),),
    "telegram": (_RequiredField("bot token", "bot_token"),),
    "whatsapp": (
        _RequiredField("phone_number_id", "phone_number_id"),
        _RequiredField("access_token", "access_token"),
    ),
    "email": (
        _RequiredField("smtp_username", "smtp_username"),
        _RequiredField("smtp_key", "smtp_key"),
        _RequiredField("email_from", "email_from"),
    ),
}


def _resolve_field(cfg: object, spec: _RequiredField) -> str:
    """Read one required field from its config section."""
    raw = cfg.get(spec.config_attr) if isinstance(cfg, dict) else getattr(cfg, spec.config_attr, None)
    return "" if is_unresolved_placeholder(raw) else str(raw).strip()


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


def missing_enabled_service_fields(config: object) -> dict[str, list[str]]:
    """Return missing typed fields for enabled optional provider services."""
    missing: dict[str, list[str]] = {}
    summarizer = getattr(config, "summarizer", None)
    local = getattr(summarizer, "local", None) if summarizer is not None else None
    if local is not None and getattr(local, "enabled", False):
        local_missing = [
            field_name
            for field_name in ("base_url", "model")
            if is_unresolved_placeholder(getattr(local, field_name, None))
        ]
        if local_missing:
            missing["summarizer.local"] = local_missing

    for section_name in ("tts", "stt"):
        section = getattr(config, section_name, None)
        if section is None or not getattr(section, "enabled", False):
            continue
        services = getattr(section, "services", None)
        elevenlabs = services.get("elevenlabs") if services else None
        if elevenlabs is not None and getattr(elevenlabs, "enabled", False):
            if is_unresolved_placeholder(getattr(elevenlabs, "api_key", None)):
                missing[f"{section_name}.services.elevenlabs"] = ["api_key"]

    return missing


def is_section_available(section: str, cfg: object) -> bool:
    """Return True when a section is enabled AND fully configured.

    The single gate downstream callers use before relying on a service/provider
    (e.g. email senders). ``cfg`` is a parsed config object or section dict.
    """
    if cfg is None:
        return False
    enabled = cfg.get("enabled", False) if isinstance(cfg, dict) else getattr(cfg, "enabled", False)
    return bool(enabled) and not missing_required_fields(section, cfg)
