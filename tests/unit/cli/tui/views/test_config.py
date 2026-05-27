"""Characterization tests for teleclaude.cli.tui.views.config.

ConfigView is a full Textual widget subclass. Most pure editing and rendering
logic is characterized in test_config_editing.py and test_config_render.py.
This file covers module-level availability plus the Adapters/Providers subtab split.
"""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.config_components.guidance import guidance_registry
from teleclaude.cli.tui.views._config_constants import _SUBTABS, Subtab
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
_LOCAL_BASE_URL_VAR = "SUMMARIZER_LOCAL_BASE_URL"
_LOCAL_BASE_URL_FIELD = "local_base_url"
_LOCAL_BASE_URL_VALUE = "http://localhost:1234/v1"
_OPENAI_MODEL_FIELD = "openai_model"
_OPENAI_MODEL_VALUE = "gpt-5-test"


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
