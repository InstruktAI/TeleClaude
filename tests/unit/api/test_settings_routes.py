"""Characterization tests for settings routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api import settings_routes


@pytest.fixture
def configured_runtime_settings() -> MagicMock:
    runtime_settings = MagicMock()
    runtime_settings.get_state.return_value = SimpleNamespace(tts=SimpleNamespace(enabled=True))
    runtime_settings.patch.return_value = SimpleNamespace(tts=SimpleNamespace(enabled=False))
    settings_routes.configure(runtime_settings)
    return runtime_settings


class TestSettingsRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_settings_reads_current_runtime_state(self, configured_runtime_settings: MagicMock) -> None:
        """Settings reads the current mutable runtime state from the configured store."""
        response = await settings_routes.get_settings()

        assert response.model_dump() == {"tts": {"enabled": True}}
        configured_runtime_settings.get_state.assert_called_once_with()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_patch_settings_applies_parsed_patch(self, configured_runtime_settings: MagicMock) -> None:
        """Patch settings delegates parsing to RuntimeSettings before applying the update."""
        with patch(
            "teleclaude.api.settings_routes.RuntimeSettings.parse_patch",
            return_value=SimpleNamespace(tts=SimpleNamespace(enabled=False)),
        ) as parse_patch:
            response = await settings_routes.patch_settings({"tts": {"enabled": False}})

        assert response.model_dump() == {"tts": {"enabled": False}}
        parse_patch.assert_called_once_with({"tts": {"enabled": False}})
        configured_runtime_settings.patch.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_patch_settings_translates_parse_errors_to_http_400(
        self,
        configured_runtime_settings: MagicMock,
    ) -> None:
        """Invalid patch bodies return an HTTP 400 instead of leaking ValueError."""
        with patch("teleclaude.api.settings_routes.RuntimeSettings.parse_patch", side_effect=ValueError("bad patch")):
            with pytest.raises(HTTPException) as exc_info:
                await settings_routes.patch_settings({"tts": {"enabled": "nope"}})

        assert exc_info.value.status_code == 400
