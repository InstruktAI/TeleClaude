"""Characterization tests for teleclaude.hooks.handlers."""

from __future__ import annotations

import pytest

from teleclaude.hooks.handlers import HandlerRegistry
from teleclaude.hooks.webhook_models import HookEvent


class TestHandlerRegistry:
    @pytest.mark.unit
    def test_returns_registered_handler_by_key(self) -> None:
        registry = HandlerRegistry()

        async def handler(_event: HookEvent) -> None:
            return None

        registry.register("whatsapp", handler)

        assert registry.get("whatsapp") is handler

    @pytest.mark.unit
    def test_missing_key_returns_none(self) -> None:
        registry = HandlerRegistry()

        assert registry.get("missing") is None

    @pytest.mark.unit
    def test_keys_reflect_registered_handlers_in_insertion_order(self) -> None:
        registry = HandlerRegistry()

        async def first(_event: HookEvent) -> None:
            return None

        async def second(_event: HookEvent) -> None:
            return None

        registry.register("first", first)
        registry.register("second", second)

        assert registry.keys() == ["first", "second"]
