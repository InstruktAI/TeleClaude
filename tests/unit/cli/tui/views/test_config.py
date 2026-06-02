"""Characterization tests for teleclaude.cli.tui.views.config.

ConfigView is a full Textual widget subclass. Most pure editing and rendering
logic is characterized in test_config_editing.py and test_config_render.py.
This file covers module-level availability plus the Adapters/Providers subtab split.
"""

from __future__ import annotations

import pytest
from rich.text import Text

from teleclaude.cli.config_handlers import _ADAPTER_ENV_VARS
from teleclaude.cli.tui.config_components.guidance import FieldGuidance, guidance_registry
from teleclaude.cli.tui.views._config_constants import _GUIDED_STEPS, _SUBTABS, Subtab
from teleclaude.cli.tui.views.config import ConfigContent, ConfigView

_ADAPTER_SECTIONS = {"discord", "telegram", "whatsapp"}
_PROVIDER_SECTIONS = {"ai", "email", "backup", "firecrawl"}
_SMTP_KEY_VAR = "SMTP_KEY"
_SMTP_KEY_FIELD = "email.smtp_key"
_SMTP_TEST_VALUE = "sk-live-test"
_SUMMARIZER_FIELDS = {
    "local_enabled",
    "local_base_url",
    "local_model",
    "provider_priority",
    "openai_model",
    "anthropic_model",
    "google_model",
}
_LOCAL_BASE_URL_VAR = "SUMMARIZER_LLM_BASE_URL"
_LOCAL_BASE_URL_FIELD = "local_base_url"
_LOCAL_BASE_URL_VALUE = "http://localhost:1234/v1"
_OPENAI_MODEL_FIELD = "openai_model"
_OPENAI_MODEL_VALUE = "gpt-5-test"
_AI_FIELD_ENV = {
    "ai.anthropic_api_key": "ANTHROPIC_API_KEY",
    "ai.openai_api_key": "OPENAI_API_KEY",
    "ai.google_api_key": "GOOGLE_API_KEY",
}
_GOOGLE_KEY_FIELD = "ai.google_api_key"
_GOOGLE_KEY_VAR = "GOOGLE_API_KEY"
_GOOGLE_KEY_VALUE = "AIza-saved"
_KNOWN_CLOUD_PROVIDERS = {"openai", "anthropic", "google"}
_PROVIDER_PRIORITY_FIELD = "provider_priority"
_CONFIGURED_PROVIDER = "google"
_INFRA_SECTIONS = {"Computer", "Redis"}
_REDIS_URL_FIELD = "redis.url"
_REDIS_URL_VAR = "REDIS_URL"
_REDIS_PASSWORD_FIELD = "redis.password"
_REDIS_PASSWORD_VAR = "REDIS_PASSWORD"
_LOG_LEVEL_VAR = "TELECLAUDE_LOG_LEVEL"


def _sections(content: ConfigContent, tab: Subtab) -> set[str]:
    return {field.key.split(".")[0] for field in content._build_reflected_fields(tab)}


@pytest.mark.unit
def test_config_view_is_importable() -> None:
    assert ConfigView is not None


@pytest.mark.unit
def test_adapters_subtab_builds_only_messaging_sections() -> None:
    content = ConfigContent()
    content._raw_config = {}
    assert _sections(content, Subtab.ADAPTERS) == _ADAPTER_SECTIONS


@pytest.mark.unit
def test_providers_subtab_builds_only_service_sections() -> None:
    content = ConfigContent()
    content._raw_config = {}
    assert _sections(content, Subtab.PROVIDERS) == _PROVIDER_SECTIONS


@pytest.mark.unit
def test_providers_subtab_resolves_env_backed_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Providers field whose value is a ${VAR} placeholder resolves to its env value via the reflected path."""
    monkeypatch.setenv(_SMTP_KEY_VAR, _SMTP_TEST_VALUE)
    content = ConfigContent()
    content._raw_config = {}
    content.active_subtab = _SUBTABS.index(Subtab.PROVIDERS)

    field = next(f for f in content.reflected_fields if f.key == _SMTP_KEY_FIELD)

    assert field.env_var == _SMTP_KEY_VAR
    assert field.value == _SMTP_TEST_VALUE


@pytest.mark.unit
def test_summarizer_subtab_builds_expected_fields() -> None:
    content = ConfigContent()
    content._raw_config = {}
    keys = {field.key for field in content._build_reflected_fields(Subtab.SUMMARIZER)}
    assert keys == _SUMMARIZER_FIELDS


@pytest.mark.unit
def test_summarizer_local_base_url_is_env_backed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_LOCAL_BASE_URL_VAR, _LOCAL_BASE_URL_VALUE)
    content = ConfigContent()
    content._raw_config = {}
    content.active_subtab = _SUBTABS.index(Subtab.SUMMARIZER)

    field = next(f for f in content.reflected_fields if f.key == _LOCAL_BASE_URL_FIELD)

    assert field.env_var == _LOCAL_BASE_URL_VAR
    assert field.value == _LOCAL_BASE_URL_VALUE


@pytest.mark.unit
def test_summarizer_model_saves_to_nested_config_section() -> None:
    content = ConfigContent()
    content._raw_config = {}
    content._apply_field_to_raw_config(_OPENAI_MODEL_FIELD, _OPENAI_MODEL_VALUE)
    assert content._raw_config["summarizer"]["openai"]["model"] == _OPENAI_MODEL_VALUE


@pytest.mark.unit
def test_summarizer_base_url_guidance_is_reachable_by_env_var() -> None:
    assert guidance_registry.get_for_env(_LOCAL_BASE_URL_VAR) is not None


@pytest.mark.unit
def test_ai_provider_fields_are_env_backed() -> None:
    content = ConfigContent()
    content._raw_config = {}
    content.active_subtab = _SUBTABS.index(Subtab.PROVIDERS)
    field_env = {f.key: f.env_var for f in content.reflected_fields if f.key in _AI_FIELD_ENV}
    assert field_env == _AI_FIELD_ENV


@pytest.mark.unit
def test_ai_provider_field_saves_to_env_not_config(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "teleclaude.cli.tui.views.config_editing.set_env_var",
        lambda name, value: calls.append((name, value)),
    )
    content = ConfigContent()
    content._raw_config = {}
    content.active_subtab = _SUBTABS.index(Subtab.PROVIDERS)
    monkeypatch.setattr(content, "refresh_data", lambda: None)
    monkeypatch.setattr(content, "refresh", lambda **_kwargs: None)

    content._save_reflected_field(_GOOGLE_KEY_FIELD, _GOOGLE_KEY_VALUE)

    assert (_GOOGLE_KEY_VAR, _GOOGLE_KEY_VALUE) in calls
    # The secret must not leak into the config.yml tree.
    assert "ai" not in content._raw_config


@pytest.mark.unit
def test_summarizer_provider_order_includes_all_known_providers() -> None:
    content = ConfigContent()
    content._raw_config = {"summarizer": {"provider_priority": [_CONFIGURED_PROVIDER]}}
    content.active_subtab = _SUBTABS.index(Subtab.SUMMARIZER)
    field = next(f for f in content.reflected_fields if f.key == _PROVIDER_PRIORITY_FIELD)
    assert set(field.value) == _KNOWN_CLOUD_PROVIDERS
    # Configured order is preserved first; missing providers append.
    assert field.value[0] == _CONFIGURED_PROVIDER


@pytest.mark.unit
def test_guidance_block_suppressed_when_no_actionable_content() -> None:
    content = ConfigContent()
    result = Text()
    content._render_guidance_block(result, FieldGuidance(description="description only, no steps"))
    assert not result.plain


@pytest.mark.unit
def test_guidance_block_renders_when_it_has_steps() -> None:
    content = ConfigContent()
    result = Text()
    content._render_guidance_block(result, FieldGuidance(description="d", steps=["do the thing"]))
    assert result.plain


@pytest.mark.unit
def test_infra_subtab_has_computer_and_redis_sections() -> None:
    content = ConfigContent()
    content._raw_config = {}
    sections = {field.section for field in content._build_reflected_fields(Subtab.INFRA)}
    assert sections == _INFRA_SECTIONS


@pytest.mark.unit
def test_infra_redis_fields_are_env_backed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_REDIS_URL_VAR, "redis://localhost:6379")
    content = ConfigContent()
    content._raw_config = {}
    content.active_subtab = _SUBTABS.index(Subtab.INFRA)
    redis_keys = {_REDIS_URL_FIELD, _REDIS_PASSWORD_FIELD}
    field_env = {f.key: f.env_var for f in content.reflected_fields if f.key in redis_keys}
    assert field_env == {_REDIS_URL_FIELD: _REDIS_URL_VAR, _REDIS_PASSWORD_FIELD: _REDIS_PASSWORD_VAR}


@pytest.mark.unit
def test_infra_step_incomplete_without_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_REDIS_URL_VAR, raising=False)
    content = ConfigContent()
    content._raw_config = {}
    content._guided_mode = True
    content._guided_step_index = _GUIDED_STEPS.index(next(s for s in _GUIDED_STEPS if s.subtab == Subtab.INFRA))
    assert content._is_current_guided_step_complete() is False


@pytest.mark.unit
def test_infra_step_complete_with_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_REDIS_URL_VAR, "redis://localhost:6379")
    content = ConfigContent()
    content._raw_config = {}
    content._guided_mode = True
    content._guided_step_index = _GUIDED_STEPS.index(next(s for s in _GUIDED_STEPS if s.subtab == Subtab.INFRA))
    assert content._is_current_guided_step_complete() is True


@pytest.mark.unit
def test_log_level_is_registered_as_env_var() -> None:
    system_vars = {info.name for info in _ADAPTER_ENV_VARS.get("system", [])}
    assert _LOG_LEVEL_VAR in system_vars


@pytest.mark.unit
def test_adapter_tab_actions_are_gated_to_adapters_subtab(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adapter-tab cycling is allowed on the Adapters subtab, not on Infra (index 0)."""
    view = ConfigView()
    # No focused content: the gate falls through to the named-subtab check.
    monkeypatch.setattr(view, "_content_or_none", lambda: None)
    # set_reactive bypasses watchers (which would query the unmounted DOM).
    view.set_reactive(ConfigView.active_subtab, _SUBTABS.index(Subtab.ADAPTERS))
    assert view.check_action("next_adapter_tab", ()) is True
    view.set_reactive(ConfigView.active_subtab, _SUBTABS.index(Subtab.INFRA))
    assert view.check_action("next_adapter_tab", ()) is False
