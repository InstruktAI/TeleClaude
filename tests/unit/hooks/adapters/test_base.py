"""Characterization tests for teleclaude.hooks.adapters.base."""

from __future__ import annotations

import pytest

from teleclaude.hooks.adapters.base import HookAdapter


class TestHookAdapterProtocol:
    @pytest.mark.unit
    def test_protocol_declares_the_runtime_adapter_attributes(self) -> None:
        assert HookAdapter.__annotations__ == {
            "agent_name": "str",
            "mint_events": "frozenset[AgentHookEventType]",
            "supports_hook_checkpoint": "bool",
        }

    @pytest.mark.unit
    def test_protocol_exposes_the_required_adapter_methods(self) -> None:
        assert hasattr(HookAdapter, "parse_input") is True
        assert hasattr(HookAdapter, "normalize_payload") is True
        assert hasattr(HookAdapter, "format_checkpoint_response") is True
        assert hasattr(HookAdapter, "format_memory_injection") is True
