"""Characterization tests for teleclaude/cli/config_handlers.py."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from teleclaude.cli.config_handlers import (
    EnvVarInfo,
    EnvVarStatus,
    _is_env_var_required,
    check_env_vars,
    generate_invite_token,
    get_adapter_env_vars,
    get_all_env_vars,
    get_required_env_vars,
    resolve_env_file_path,
    set_env_var,
)

# ---------------------------------------------------------------------------
# generate_invite_token
# ---------------------------------------------------------------------------


def test_generate_invite_token_has_inv_prefix() -> None:
    token = generate_invite_token()
    assert token.startswith("inv_")


def test_generate_invite_token_has_expected_length() -> None:
    token = generate_invite_token()
    # "inv_" + 16 hex chars = 20 chars
    assert len(token) == 20


def test_generate_invite_token_is_unique() -> None:
    tokens = {generate_invite_token() for _ in range(10)}
    assert len(tokens) == 10


# ---------------------------------------------------------------------------
# get_adapter_env_vars
# ---------------------------------------------------------------------------


def test_get_adapter_env_vars_returns_telegram_vars() -> None:
    vars_list = get_adapter_env_vars("telegram")
    names = [v.name for v in vars_list]
    assert "TELEGRAM_BOT_TOKEN" in names


def test_get_adapter_env_vars_returns_empty_for_unknown_adapter() -> None:
    result = get_adapter_env_vars("nonexistent-adapter")
    assert result == []


def test_get_adapter_env_vars_returns_discord_vars() -> None:
    vars_list = get_adapter_env_vars("discord")
    names = [v.name for v in vars_list]
    assert "DISCORD_BOT_TOKEN" in names


# ---------------------------------------------------------------------------
# get_all_env_vars / get_required_env_vars
# ---------------------------------------------------------------------------


def test_get_all_env_vars_returns_dict_by_service() -> None:
    all_vars = get_all_env_vars()
    assert isinstance(all_vars, dict)
    assert "telegram" in all_vars
    assert "discord" in all_vars


def test_get_required_env_vars_is_alias_for_get_all_env_vars() -> None:
    assert get_required_env_vars() == get_all_env_vars()


# ---------------------------------------------------------------------------
# check_env_vars
# ---------------------------------------------------------------------------


def test_check_env_vars_returns_list_of_env_var_status() -> None:
    statuses = check_env_vars()
    assert isinstance(statuses, list)
    assert all(isinstance(s, EnvVarStatus) for s in statuses)


def test_check_env_vars_reflects_set_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-value")
    statuses = check_env_vars()
    telegram_status = next((s for s in statuses if s.info.name == "TELEGRAM_BOT_TOKEN"), None)
    assert telegram_status is not None
    assert telegram_status.is_set is True


def test_check_env_vars_reflects_unset_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    statuses = check_env_vars()
    telegram_status = next((s for s in statuses if s.info.name == "TELEGRAM_BOT_TOKEN"), None)
    assert telegram_status is not None
    assert telegram_status.is_set is False


# ---------------------------------------------------------------------------
# resolve_env_file_path
# ---------------------------------------------------------------------------


def test_resolve_env_file_path_uses_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELECLAUDE_ENV_PATH", str(tmp_path / ".env"))
    result = resolve_env_file_path()
    assert result == tmp_path / ".env"


def test_resolve_env_file_path_uses_explicit_arg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TELECLAUDE_ENV_PATH", raising=False)
    explicit_path = tmp_path / "custom.env"
    result = resolve_env_file_path(explicit_path)
    assert result == explicit_path


# ---------------------------------------------------------------------------
# set_env_var
# ---------------------------------------------------------------------------


def test_set_env_var_writes_new_var_to_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    monkeypatch.delenv("TELECLAUDE_ENV_PATH", raising=False)
    set_env_var("MY_TEST_KEY", "my_value", env_path=env_file)
    content = env_file.read_text()
    assert "MY_TEST_KEY=my_value" in content


def test_set_env_var_updates_existing_var_in_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MY_KEY=old_value\n")
    monkeypatch.delenv("TELECLAUDE_ENV_PATH", raising=False)
    set_env_var("MY_KEY", "new_value", env_path=env_file)
    content = env_file.read_text()
    assert "new_value" in content
    assert "old_value" not in content


def test_set_env_var_updates_os_environ(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    monkeypatch.delenv("TELECLAUDE_ENV_PATH", raising=False)
    set_env_var("MY_UNIQUE_TEST_KEY", "set_value", env_path=env_file)
    assert os.environ.get("MY_UNIQUE_TEST_KEY") == "set_value"
    monkeypatch.delenv("MY_UNIQUE_TEST_KEY", raising=False)


def test_set_env_var_rejects_name_with_equals_sign(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    with pytest.raises(ValueError):
        set_env_var("KEY=INVALID", "value", env_path=env_file)


def test_set_env_var_rejects_name_with_newline(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    with pytest.raises(ValueError):
        set_env_var("KEY\nINVALID", "value", env_path=env_file)


def test_set_env_var_rejects_value_with_newline(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    with pytest.raises(ValueError):
        set_env_var("VALID_KEY", "line1\nline2", env_path=env_file)


# ---------------------------------------------------------------------------
# _is_env_var_required — adapter-aware env var gating
# ---------------------------------------------------------------------------


def _info(name: str, group: str) -> EnvVarInfo:
    return EnvVarInfo(name=name, adapter=group, description="", example="")


def _config(**adapters: object) -> SimpleNamespace:
    """Build a minimal Config stand-in with the adapter attributes requested."""
    return SimpleNamespace(**adapters)


# redis: REDIS_URL required, REDIS_PASSWORD opt-in (auth-less local Redis default)


def test_redis_url_is_required_even_without_app_config() -> None:
    assert _is_env_var_required(_info("REDIS_URL", "redis"), None) is True


def test_redis_password_is_optional() -> None:
    assert _is_env_var_required(_info("REDIS_PASSWORD", "redis"), None) is False


# app_config absent: every non-redis group falls back to "not required"


def test_non_redis_groups_are_optional_when_app_config_missing() -> None:
    for group in ("telegram", "discord", "whatsapp", "email", "voice", "ai", "backup", "system"):
        assert _is_env_var_required(_info("X", group), None) is False


# telegram / discord / whatsapp / email: gated by config.<adapter>.enabled


@pytest.mark.parametrize("group,attr", [("telegram", "telegram"), ("discord", "discord"), ("whatsapp", "whatsapp")])
def test_simple_adapter_required_when_enabled(group: str, attr: str) -> None:
    enabled_cfg = _config(**{attr: SimpleNamespace(enabled=True)})
    disabled_cfg = _config(**{attr: SimpleNamespace(enabled=False)})
    assert _is_env_var_required(_info("X", group), enabled_cfg) is True
    assert _is_env_var_required(_info("X", group), disabled_cfg) is False


def test_email_required_when_enabled() -> None:
    enabled = _config(email=SimpleNamespace(enabled=True))
    disabled = _config(email=SimpleNamespace(enabled=False))
    missing = _config(email=None)
    assert _is_env_var_required(_info("EMAIL_FROM", "email"), enabled) is True
    assert _is_env_var_required(_info("EMAIL_FROM", "email"), disabled) is False
    assert _is_env_var_required(_info("EMAIL_FROM", "email"), missing) is False


# voice: ELEVENLABS_API_KEY required only when elevenlabs service is enabled on TTS or STT


def test_voice_optional_when_tts_and_stt_disabled() -> None:
    cfg = _config(
        tts=SimpleNamespace(enabled=False, services={}),
        stt=SimpleNamespace(enabled=False, services={}),
    )
    assert _is_env_var_required(_info("ELEVENLABS_API_KEY", "voice"), cfg) is False


def test_voice_required_when_tts_has_enabled_elevenlabs() -> None:
    cfg = _config(
        tts=SimpleNamespace(enabled=True, services={"elevenlabs": SimpleNamespace(enabled=True)}),
        stt=SimpleNamespace(enabled=False, services=None),
    )
    assert _is_env_var_required(_info("ELEVENLABS_API_KEY", "voice"), cfg) is True


def test_voice_required_when_stt_has_enabled_elevenlabs() -> None:
    cfg = _config(
        tts=SimpleNamespace(enabled=False, services=None),
        stt=SimpleNamespace(enabled=True, services={"elevenlabs": SimpleNamespace(enabled=True)}),
    )
    assert _is_env_var_required(_info("ELEVENLABS_API_KEY", "voice"), cfg) is True


def test_voice_optional_when_elevenlabs_service_disabled() -> None:
    cfg = _config(
        tts=SimpleNamespace(enabled=True, services={"elevenlabs": SimpleNamespace(enabled=False)}),
        stt=SimpleNamespace(enabled=False, services=None),
    )
    assert _is_env_var_required(_info("ELEVENLABS_API_KEY", "voice"), cfg) is False


# ai: summarizer local vars gated by summarizer.local.enabled; cloud keys always opt-in


def test_summarizer_local_vars_required_when_local_enabled() -> None:
    cfg = _config(summarizer=SimpleNamespace(local=SimpleNamespace(enabled=True)))
    assert _is_env_var_required(_info("SUMMARIZER_LLM_BASE_URL", "ai"), cfg) is True
    assert _is_env_var_required(_info("SUMMARIZER_LLM_MODEL", "ai"), cfg) is True


def test_summarizer_local_vars_optional_when_local_disabled() -> None:
    cfg = _config(summarizer=SimpleNamespace(local=SimpleNamespace(enabled=False)))
    assert _is_env_var_required(_info("SUMMARIZER_LLM_BASE_URL", "ai"), cfg) is False


def test_summarizer_cloud_keys_always_optional() -> None:
    cfg_local_on = _config(summarizer=SimpleNamespace(local=SimpleNamespace(enabled=True)))
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        assert _is_env_var_required(_info(key, "ai"), cfg_local_on) is False


# backup / firecrawl / system: no enable flag → always opt-in


def test_unflagged_groups_are_always_optional() -> None:
    cfg = _config()
    for group in ("backup", "firecrawl", "system"):
        assert _is_env_var_required(_info("X", group), cfg) is False
