"""Shared adapter-configuration validation.

One source of truth for "is an enabled adapter actually configured" — used by
both the startup path (decide whether to start an adapter) and the config TUI
(refuse to persist an enabled-but-incomplete section). Keeping this in one place
means the rule cannot drift between the two surfaces.
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
class _CredSpec:
    """A required credential and where it resolves from.

    ``config_attr`` is read off the adapter config object first; if it is empty
    or an unresolved placeholder, ``env_var`` (if any) is consulted. ``label`` is
    the human-facing field name surfaced in the "not configured" warning.
    """

    label: str
    config_attr: str | None
    env_var: str | None


# Per-adapter required credentials, encoding each adapter's real resolution path
# (discord: config token or env; telegram: env-only; whatsapp: config or env).
_ADAPTER_CREDS: dict[str, tuple[_CredSpec, ...]] = {
    "discord": (_CredSpec("token", "token", "DISCORD_BOT_TOKEN"),),
    "telegram": (_CredSpec("bot token", None, "TELEGRAM_BOT_TOKEN"),),
    "whatsapp": (
        _CredSpec("phone_number_id", "phone_number_id", "WHATSAPP_PHONE_NUMBER_ID"),
        _CredSpec("access_token", "access_token", "WHATSAPP_ACCESS_TOKEN"),
    ),
}


def _resolve_cred(cfg: object, spec: _CredSpec) -> str:
    """Resolve a credential to its effective value (config field, else env)."""
    if spec.config_attr is not None:
        raw = getattr(cfg, spec.config_attr, None)
        if not is_unresolved_placeholder(raw):
            return str(raw).strip()
    if spec.env_var:
        return os.getenv(spec.env_var, "").strip()
    return ""


def validate_adapter_config(name: str, cfg: object) -> list[str]:
    """Return the required credential labels that are missing/unconfigured.

    An empty list means the adapter is fully configured. Adapters with no
    credential requirements always return an empty list.
    """
    return [spec.label for spec in _ADAPTER_CREDS.get(name, ()) if not _resolve_cred(cfg, spec)]
