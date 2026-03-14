"""Characterization tests for teleclaude.core.origins."""

from __future__ import annotations

import pytest

from teleclaude.core.origins import InputOrigin


class TestInputOrigin:
    @pytest.mark.unit
    def test_telegram_value(self):
        assert InputOrigin.TELEGRAM.value == "telegram"

    @pytest.mark.unit
    def test_discord_value(self):
        assert InputOrigin.DISCORD.value == "discord"

    @pytest.mark.unit
    def test_whatsapp_value(self):
        assert InputOrigin.WHATSAPP.value == "whatsapp"

    @pytest.mark.unit
    def test_redis_value(self):
        assert InputOrigin.REDIS.value == "redis"

    @pytest.mark.unit
    def test_api_value(self):
        assert InputOrigin.API.value == "api"

    @pytest.mark.unit
    def test_terminal_value(self):
        assert InputOrigin.TERMINAL.value == "terminal"

    @pytest.mark.unit
    def test_hook_value(self):
        assert InputOrigin.HOOK.value == "hook"

    @pytest.mark.unit
    def test_is_str_subclass(self):
        # InputOrigin(str, Enum) — inherits from str so instance is a str
        assert isinstance(InputOrigin.TELEGRAM, str)

    @pytest.mark.unit
    def test_equality_with_string(self):
        assert InputOrigin.API == "api"  # type: ignore[comparison-overlap]

    @pytest.mark.unit
    def test_all_origins_have_string_values(self):
        for origin in InputOrigin:
            assert isinstance(origin.value, str)
            assert origin.value
