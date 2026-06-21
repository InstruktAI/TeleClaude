"""Unset ``${VAR}`` placeholders fall back to Python defaults, not literal strings."""

from __future__ import annotations

from teleclaude.cli.config_handlers import EnvVarInfo, _is_env_var_required
from teleclaude.config import DEFAULT_CONFIG, deep_merge, strip_unset_placeholders
from teleclaude.utils import expand_env_vars

PROD_REDIS_URL = "rediss://prod.example:6478"
EXPLICIT_REDIS_URL = "redis://explicit:6379"


def _load(
    raw: dict[str, object],  # guard: loose-dict - YAML config tree
) -> dict[str, object]:  # guard: loose-dict - YAML config tree
    """Mirror the loader: expand env vars, strip unresolved placeholders, merge defaults."""
    user = strip_unset_placeholders(expand_env_vars(raw))
    return deep_merge(DEFAULT_CONFIG, user)


def test_unset_placeholder_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)

    merged = _load({"redis": {"url": "${REDIS_URL}", "password": "${REDIS_PASSWORD}"}})

    assert merged["redis"]["url"] == DEFAULT_CONFIG["redis"]["url"]  # type: ignore[index]
    assert merged["redis"]["password"] is None  # type: ignore[index]


def test_set_placeholder_overrides_default(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_URL", PROD_REDIS_URL)

    merged = _load({"redis": {"url": "${REDIS_URL}"}})

    assert merged["redis"]["url"] == PROD_REDIS_URL  # type: ignore[index]


def test_literal_value_is_preserved(monkeypatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)

    merged = _load({"redis": {"url": EXPLICIT_REDIS_URL}})

    assert merged["redis"]["url"] == EXPLICIT_REDIS_URL  # type: ignore[index]


def test_redis_url_not_required() -> None:
    info = EnvVarInfo("REDIS_URL", "redis", "Redis connection URL", DEFAULT_CONFIG["redis"]["url"])  # type: ignore[index]
    assert _is_env_var_required(info, app_config=None) is False
