from __future__ import annotations

import pytest

from teleclaude.cli.tui.config_components.guidance import GuidanceRegistry, get_guidance_for_env


@pytest.mark.unit
def test_guidance_registry_returns_registered_field_metadata() -> None:
    registry = GuidanceRegistry()

    guidance = registry.get("adapters.telegram.bot_token")

    assert guidance is not None
    assert bool(guidance.description) is True
    assert len(guidance.steps) == 3
    assert guidance.format_example is not None
    assert guidance.validation_hint is not None
    assert registry.get("missing.field") is None


@pytest.mark.unit
def test_get_guidance_for_env_maps_known_environment_variables() -> None:
    assert get_guidance_for_env("TELEGRAM_BOT_TOKEN") is not None
    assert get_guidance_for_env("NOPE") is None
