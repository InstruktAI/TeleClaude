"""Unset ``${VAR}`` placeholders fall back to Python defaults, not literal strings.

These drive the real loader boundary ``_load_config_from_disk`` so the fix wiring
(``strip_unset_placeholders`` in the load pipeline) is actually exercised — removing
it from the loader makes ``test_loader_applies_default_when_redis_url_unset`` fail.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import teleclaude.config as config_mod
from teleclaude.cli.config_handlers import EnvVarInfo, _is_env_var_required
from teleclaude.config import DEFAULT_CONFIG

PROD_REDIS_URL = "rediss://prod.example:6478"
DEFAULT_REDIS_URL = str(
    cast("dict[str, object]", DEFAULT_CONFIG["redis"])["url"]  # guard: loose-dict - read default from config blueprint
)

# Smallest config that builds: one enabled agent + redis placeholders. Every other
# section falls back to DEFAULT_CONFIG, so no adapter secret is needed.
_MINIMAL_CONFIG = """\
agents:
  default: claude
  claude:
    enabled: true
redis:
  url: ${REDIS_URL}
  password: ${REDIS_PASSWORD}
"""


def _write_config(tmp_path: Path) -> Path:
    dst = tmp_path / "config.yml"
    dst.write_text(_MINIMAL_CONFIG, encoding="utf-8")
    return dst


def _neutralize_dotenv(tmp_path: Path, monkeypatch) -> None:
    """Stop the loader's _refresh_dotenv from re-injecting vars from the real .env."""
    monkeypatch.setattr(config_mod, "_dotenv_path", tmp_path / "absent.env")
    monkeypatch.setattr(config_mod, "_dotenv_managed_keys", set())


def test_loader_applies_default_when_redis_url_unset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    _neutralize_dotenv(tmp_path, monkeypatch)

    cfg = config_mod._load_config_from_disk(_write_config(tmp_path))

    assert cfg.redis.url == DEFAULT_REDIS_URL
    assert cfg.redis.password is None


def test_loader_uses_env_when_redis_url_set(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REDIS_URL", PROD_REDIS_URL)
    _neutralize_dotenv(tmp_path, monkeypatch)

    cfg = config_mod._load_config_from_disk(_write_config(tmp_path))

    assert cfg.redis.url == PROD_REDIS_URL


def test_redis_url_not_required() -> None:
    info = EnvVarInfo("REDIS_URL", "redis", "Redis connection URL", DEFAULT_REDIS_URL)
    assert _is_env_var_required(info, app_config=None) is False
