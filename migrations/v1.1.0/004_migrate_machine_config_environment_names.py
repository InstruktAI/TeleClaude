"""Advance machine-config placeholders to their schema-derived environment names."""

from __future__ import annotations

import yaml

from teleclaude.config._environment import reconcile_environment_values
from teleclaude.file_transaction import file_transaction
from teleclaude.paths import ENV_PATH, MACHINE_CONFIG_PATH

_PLACEHOLDER_RENAMES: dict[tuple[str, ...], tuple[str, str]] = {
    ("summarizer", "local", "base_url"): ("SUMMARIZER_LLM_BASE_URL", "SUMMARIZER_LOCAL_BASE_URL"),
    ("summarizer", "local", "model"): ("SUMMARIZER_LLM_MODEL", "SUMMARIZER_LOCAL_MODEL"),
    ("summarizer", "openai", "api_key"): ("OPENAI_API_KEY", "SUMMARIZER_OPENAI_API_KEY"),
    ("summarizer", "anthropic", "api_key"): ("ANTHROPIC_API_KEY", "SUMMARIZER_ANTHROPIC_API_KEY"),
    ("summarizer", "google", "api_key"): ("GOOGLE_API_KEY", "SUMMARIZER_GOOGLE_API_KEY"),
    ("discord", "token"): ("DISCORD_BOT_TOKEN", "DISCORD_TOKEN"),
    ("email", "smtp_username"): ("SMTP_USERNAME", "EMAIL_SMTP_USERNAME"),
    ("email", "smtp_key"): ("SMTP_KEY", "EMAIL_SMTP_KEY"),
    ("email", "email_from"): ("EMAIL_FROM", "EMAIL_EMAIL_FROM"),
    ("email", "reply_to"): ("EMAIL_REPLYTO", "EMAIL_REPLY_TO"),
    ("email", "smtp_relay"): ("SMTP_RELAY", "EMAIL_SMTP_RELAY"),
}
_SHARED_CANONICAL_NAMES = frozenset({"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"})


def check() -> bool:
    """Return whether no current machine-config reference names a retired variable."""
    if not MACHINE_CONFIG_PATH.exists():
        return True
    content = MACHINE_CONFIG_PATH.read_text(encoding="utf-8")
    return not any(f"${{{old_name}}}" in content for old_name, _ in _PLACEHOLDER_RENAMES.values())


def migrate() -> bool:
    """Move aliases before switching config placeholders, then retire unused aliases."""
    if not MACHINE_CONFIG_PATH.exists():
        return True
    with file_transaction(MACHINE_CONFIG_PATH) as config_transaction:
        raw = yaml.safe_load(config_transaction.read_text()) or {}
        if not isinstance(raw, dict):
            raise ValueError("Machine configuration must be a mapping")
        environment = _read_environment_text(ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else "")
        migrated = _replace_placeholders(raw)
        additions = _preflight_additions(environment, raw)
        reconcile_environment_values(ENV_PATH, additions, frozenset())
        config_transaction.replace_text(yaml.safe_dump(migrated, sort_keys=False))
        removals = _retired_aliases(migrated)
        reconcile_environment_values(ENV_PATH, {}, removals)
    return True


def _read_environment_text(text: str) -> dict[str, str]:
    """Read assignment values without resolving or exposing them."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        name, separator, value = line.partition("=")
        if separator and name:
            values[name.removeprefix("export ")] = value
    return values


def _preflight_additions(environment: dict[str, str], raw: dict[str, object]) -> dict[str, str]:
    """Reject divergent aliases before either file is mutated."""
    additions: dict[str, str] = {}
    for old_name, new_name in _PLACEHOLDER_RENAMES.values():
        old_value = environment.get(old_name)
        new_value = environment.get(new_name)
        if old_value is not None and new_value is not None and old_value != new_value:
            raise ValueError(f"Conflicting environment aliases: {old_name}, {new_name}")
        if old_value is not None and new_value is None:
            additions[new_name] = f"${{{old_name}}}" if old_name in _SHARED_CANONICAL_NAMES else old_value
    return additions


def _replace_placeholders(value: object, path: tuple[str, ...] = ()) -> object:
    """Replace retired placeholders recursively while preserving every config path."""
    if isinstance(value, dict):
        return {key: _replace_placeholders(child, (*path, str(key))) for key, child in value.items()}
    if isinstance(value, list):
        return [_replace_placeholders(child, path) for child in value]
    if isinstance(value, str):
        rename = _PLACEHOLDER_RENAMES.get(path)
        if rename is not None:
            old_name, new_name = rename
            value = value.replace(f"${{{old_name}}}", f"${{{new_name}}}")
    return value


def _retired_aliases(raw: object) -> frozenset[str]:
    """Remove aliases only after no surviving config reference needs them."""
    rendered = yaml.safe_dump(raw, sort_keys=False)
    old_names = {old_name for old_name, _ in _PLACEHOLDER_RENAMES.values()}
    return frozenset(
        name for name in old_names if name not in _SHARED_CANONICAL_NAMES and f"${{{name}}}" not in rendered
    )
