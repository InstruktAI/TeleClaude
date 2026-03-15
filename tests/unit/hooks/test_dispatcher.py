"""Characterization tests for teleclaude.hooks.dispatcher."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import pytest

from teleclaude.core.models import JsonDict
from teleclaude.hooks.dispatcher import HookDispatcher
from teleclaude.hooks.webhook_models import Contract, HookEvent, Target


@dataclass
class _ContractRegistryStub:
    matches: list[Contract] = field(default_factory=list)
    seen_events: list[HookEvent] = field(default_factory=list)

    def match(self, event: HookEvent) -> list[Contract]:
        self.seen_events.append(event)
        return list(self.matches)


@dataclass
class _HandlerRegistryStub:
    handlers: dict[str, Callable[[HookEvent], Awaitable[None]]] = field(default_factory=dict)

    def get(self, key: str) -> Callable[[HookEvent], Awaitable[None]] | None:
        return self.handlers.get(key)


class _EnqueueRecorder:
    def __init__(self) -> None:
        self.calls: list[JsonDict] = []

    async def __call__(
        self,
        *,
        contract_id: str,
        event_json: str,
        target_url: str,
        target_secret: str | None,
    ) -> None:
        self.calls.append(
            {
                "contract_id": contract_id,
                "event_json": event_json,
                "target_url": target_url,
                "target_secret": target_secret,
            }
        )


def _make_event() -> HookEvent:
    return HookEvent(
        source="github",
        type="pull_request",
        timestamp="2025-01-01T00:00:00+00:00",
        properties={"repo": "owner/repo"},
    )


class TestHookDispatcher:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_without_touching_targets_when_no_contracts_match(self) -> None:
        contracts = _ContractRegistryStub()
        handlers = _HandlerRegistryStub()
        enqueue = _EnqueueRecorder()
        dispatcher = HookDispatcher(contracts, handlers, enqueue)

        await dispatcher.dispatch(_make_event())

        assert contracts.seen_events == [_make_event()]
        assert enqueue.calls == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_dispatches_matching_handler_targets(self) -> None:
        seen_events: list[HookEvent] = []

        async def _handler(event: HookEvent) -> None:
            seen_events.append(event)

        contract = Contract(id="contract-1", target=Target(handler="internal"))
        dispatcher = HookDispatcher(
            _ContractRegistryStub(matches=[contract]),
            _HandlerRegistryStub(handlers={"internal": _handler}),
            _EnqueueRecorder(),
        )
        event = _make_event()

        await dispatcher.dispatch(event)

        assert seen_events == [event]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_enqueues_matching_url_targets_with_serialized_event_payload(self) -> None:
        contract = Contract(
            id="contract-2",
            target=Target(url="https://example.test/hook", secret="top-secret"),
        )
        enqueue = _EnqueueRecorder()
        event = _make_event()
        dispatcher = HookDispatcher(
            _ContractRegistryStub(matches=[contract]),
            _HandlerRegistryStub(),
            enqueue,
        )

        await dispatcher.dispatch(event)

        assert enqueue.calls == [
            {
                "contract_id": "contract-2",
                "event_json": event.to_json(),
                "target_url": "https://example.test/hook",
                "target_secret": "top-secret",
            }
        ]
