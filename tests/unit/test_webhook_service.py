"""Comprehensive tests for the webhook service subsystem."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.hooks.webhook_models import Contract, HookEvent, PropertyCriterion, Target

# ── Model tests ──────────────────────────────────────────────────────


class TestHookEvent:
    def test_create_event(self) -> None:
        event = HookEvent(source="agent", type="session.started", timestamp="2024-01-01T00:00:00Z")
        assert event.source == "agent"
        assert event.type == "session.started"
        assert event.properties == {}
        assert event.payload == {}

    def test_event_with_properties(self) -> None:
        event = HookEvent(
            source="agent",
            type="tool.completed",
            timestamp="2024-01-01T00:00:00Z",
            properties={"tool_name": "bash", "session_id": "abc123"},
            payload={"result": "ok"},
        )
        assert event.properties["tool_name"] == "bash"
        assert event.payload["result"] == "ok"

    def test_event_json_roundtrip(self) -> None:
        event = HookEvent(
            source="system",
            type="error.critical",
            timestamp="2024-01-01T00:00:00Z",
            properties={"severity": "critical"},
        )
        json_str = event.to_json()
        restored = HookEvent.from_json(json_str)
        assert restored.source == event.source
        assert restored.type == event.type
        assert restored.properties == event.properties

    def test_event_now_factory(self) -> None:
        event = HookEvent.now(source="test", type="test.event")
        assert event.source == "test"
        assert event.type == "test.event"
        assert event.timestamp  # should be non-empty ISO string


class TestContract:
    def test_contract_json_roundtrip(self) -> None:
        contract = Contract(
            id="test-1",
            target=Target(url="https://example.com/hook", secret="s3cret"),
            source_criterion=PropertyCriterion(match="agent"),
            type_criterion=PropertyCriterion(pattern="session.*"),
            properties={"severity": PropertyCriterion(match=["critical", "error"])},
        )
        json_str = contract.to_json()
        restored = Contract.from_json(json_str)
        assert restored.id == "test-1"
        assert restored.target.url == "https://example.com/hook"
        assert restored.target.secret == "s3cret"
        assert restored.source_criterion is not None
        assert restored.source_criterion.match == "agent"
        assert restored.type_criterion is not None
        assert restored.type_criterion.pattern == "session.*"
        assert restored.properties["severity"].match == ["critical", "error"]

    def test_contract_with_handler_target(self) -> None:
        contract = Contract(id="h-1", target=Target(handler="my_handler"), source="programmatic")
        assert contract.target.handler == "my_handler"
        assert contract.target.url is None


# ── Matcher tests ────────────────────────────────────────────────────


class TestMatcher:
    def setup_method(self) -> None:
        from teleclaude.hooks.matcher import match_criterion, match_event

        self.match_criterion = match_criterion
        self.match_event = match_event

    def test_exact_match(self) -> None:
        assert self.match_criterion("agent", PropertyCriterion(match="agent")) is True
        assert self.match_criterion("system", PropertyCriterion(match="agent")) is False

    def test_multi_value_match(self) -> None:
        c = PropertyCriterion(match=["critical", "error"])
        assert self.match_criterion("critical", c) is True
        assert self.match_criterion("error", c) is True
        assert self.match_criterion("warning", c) is False

    def test_wildcard_pattern(self) -> None:
        c = PropertyCriterion(pattern="session.*")
        assert self.match_criterion("session.started", c) is True
        assert self.match_criterion("session.closed", c) is True
        assert self.match_criterion("agent.tool.done", c) is False

    def test_required_presence(self) -> None:
        c = PropertyCriterion(required=True)
        assert self.match_criterion("anything", c) is True
        assert self.match_criterion(None, c) is False

    def test_optional_criterion(self) -> None:
        c = PropertyCriterion(required=False)
        assert self.match_criterion(None, c) is True
        assert self.match_criterion("value", c) is True

    def test_missing_property(self) -> None:
        assert self.match_criterion(None, PropertyCriterion(match="agent")) is False

    def test_match_event_all_pass(self) -> None:
        event = HookEvent(
            source="agent",
            type="session.started",
            timestamp="2024-01-01T00:00:00Z",
            properties={"severity": "critical"},
        )
        contract = Contract(
            id="c1",
            target=Target(handler="h1"),
            source_criterion=PropertyCriterion(match="agent"),
            type_criterion=PropertyCriterion(pattern="session.*"),
            properties={"severity": PropertyCriterion(match=["critical", "error"])},
        )
        assert self.match_event(event, contract) is True

    def test_match_event_source_fails(self) -> None:
        event = HookEvent(source="system", type="session.started", timestamp="2024-01-01T00:00:00Z")
        contract = Contract(
            id="c2",
            target=Target(handler="h1"),
            source_criterion=PropertyCriterion(match="agent"),
        )
        assert self.match_event(event, contract) is False

    def test_match_event_no_criteria(self) -> None:
        event = HookEvent(source="agent", type="anything", timestamp="2024-01-01T00:00:00Z")
        contract = Contract(id="c3", target=Target(handler="h1"))
        assert self.match_event(event, contract) is True

    def test_match_event_optional_property(self) -> None:
        event = HookEvent(source="agent", type="test", timestamp="2024-01-01T00:00:00Z")
        contract = Contract(
            id="c4",
            target=Target(handler="h1"),
            properties={"optional_prop": PropertyCriterion(required=False)},
        )
        assert self.match_event(event, contract) is True


# ── Handler registry tests ───────────────────────────────────────────


class TestHandlerRegistry:
    def test_register_and_get(self) -> None:
        from teleclaude.hooks.handlers import HandlerRegistry

        registry = HandlerRegistry()
        handler = AsyncMock()
        registry.register("test_handler", handler)
        assert registry.get("test_handler") is handler
        assert registry.get("nonexistent") is None

    def test_keys(self) -> None:
        from teleclaude.hooks.handlers import HandlerRegistry

        registry = HandlerRegistry()
        registry.register("a", AsyncMock())
        registry.register("b", AsyncMock())
        assert sorted(registry.keys()) == ["a", "b"]


# ── Dispatcher tests ─────────────────────────────────────────────────


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_to_internal_handler(self) -> None:
        from teleclaude.hooks.dispatcher import HookDispatcher
        from teleclaude.hooks.handlers import HandlerRegistry
        from teleclaude.hooks.registry import ContractRegistry

        handler = AsyncMock()
        handler_registry = HandlerRegistry()
        handler_registry.register("my_handler", handler)

        contract_registry = ContractRegistry()
        contract_registry._cache["c1"] = Contract(
            id="c1",
            target=Target(handler="my_handler"),
            source_criterion=PropertyCriterion(match="agent"),
        )

        enqueue = AsyncMock()
        dispatcher = HookDispatcher(contract_registry, handler_registry, enqueue)

        event = HookEvent.now(source="agent", type="test")
        await dispatcher.dispatch(event)

        handler.assert_called_once_with(event)
        enqueue.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_to_external_url(self) -> None:
        from teleclaude.hooks.dispatcher import HookDispatcher
        from teleclaude.hooks.handlers import HandlerRegistry
        from teleclaude.hooks.registry import ContractRegistry

        handler_registry = HandlerRegistry()
        contract_registry = ContractRegistry()
        contract_registry._cache["c2"] = Contract(
            id="c2",
            target=Target(url="https://example.com/hook", secret="key"),
        )

        enqueue = AsyncMock()
        dispatcher = HookDispatcher(contract_registry, handler_registry, enqueue)

        event = HookEvent.now(source="system", type="error")
        await dispatcher.dispatch(event)

        enqueue.assert_called_once()
        call_kwargs = enqueue.call_args[1]
        assert call_kwargs["contract_id"] == "c2"
        assert call_kwargs["target_url"] == "https://example.com/hook"
        assert call_kwargs["target_secret"] == "key"

    @pytest.mark.asyncio
    async def test_dispatch_no_match(self) -> None:
        from teleclaude.hooks.dispatcher import HookDispatcher
        from teleclaude.hooks.handlers import HandlerRegistry
        from teleclaude.hooks.registry import ContractRegistry

        contract_registry = ContractRegistry()
        contract_registry._cache["c3"] = Contract(
            id="c3",
            target=Target(handler="h1"),
            source_criterion=PropertyCriterion(match="agent"),
        )

        handler_registry = HandlerRegistry()
        enqueue = AsyncMock()
        dispatcher = HookDispatcher(contract_registry, handler_registry, enqueue)

        event = HookEvent.now(source="system", type="test")
        await dispatcher.dispatch(event)

        enqueue.assert_not_called()


# ── Delivery worker tests ────────────────────────────────────────────


class TestDeliveryWorker:
    def test_compute_signature(self) -> None:
        from teleclaude.hooks.delivery import compute_signature

        sig = compute_signature(b'{"test": true}', "secret")
        assert sig.startswith("sha256=")
        assert len(sig) > 10

    def test_compute_backoff(self) -> None:
        from teleclaude.hooks.delivery import compute_backoff

        assert compute_backoff(1) == 1.0
        assert compute_backoff(2) == 2.0
        assert compute_backoff(3) == 4.0
        assert compute_backoff(7) == 60.0  # capped


# ── Contract registry tests ──────────────────────────────────────────


class TestContractRegistry:
    def test_match_returns_matching_contracts(self) -> None:
        from teleclaude.hooks.registry import ContractRegistry

        registry = ContractRegistry()
        registry._cache["c1"] = Contract(
            id="c1",
            target=Target(handler="h1"),
            source_criterion=PropertyCriterion(match="agent"),
        )
        registry._cache["c2"] = Contract(
            id="c2",
            target=Target(handler="h2"),
            source_criterion=PropertyCriterion(match="system"),
        )

        event = HookEvent.now(source="agent", type="test")
        matches = registry.match(event)
        assert len(matches) == 1
        assert matches[0].id == "c1"

    def test_list_properties_vocabulary(self) -> None:
        from teleclaude.hooks.registry import ContractRegistry

        registry = ContractRegistry()
        registry._cache["c1"] = Contract(
            id="c1",
            target=Target(handler="h1"),
            source_criterion=PropertyCriterion(match="agent"),
            properties={"severity": PropertyCriterion(match=["critical", "error"])},
        )
        registry._cache["c2"] = Contract(
            id="c2",
            target=Target(handler="h2"),
            type_criterion=PropertyCriterion(match="session.started"),
        )

        vocab = registry.list_properties()
        assert "source" in vocab
        assert "agent" in vocab["source"]
        assert "severity" in vocab
        assert "critical" in vocab["severity"]
        assert "type" in vocab
        assert "session.started" in vocab["type"]


# ── DB CRUD tests ────────────────────────────────────────────────────


class TestWebhookDbCrud:
    @pytest.mark.asyncio
    async def test_webhook_contract_lifecycle(self, tmp_path: Path) -> None:
        from teleclaude.core.db import Db

        test_db = Db(str(tmp_path / "test.db"))
        await test_db.initialize()

        contract = Contract(id="test-c", target=Target(handler="h1"), source="api")
        await test_db.upsert_webhook_contract("test-c", contract.to_json(), "api")

        rows = await test_db.list_webhook_contracts(active_only=True)
        assert len(rows) == 1
        assert rows[0].id == "test-c"

        deactivated = await test_db.deactivate_webhook_contract("test-c")
        assert deactivated is True

        rows = await test_db.list_webhook_contracts(active_only=True)
        assert len(rows) == 0

        await test_db.close()

    @pytest.mark.asyncio
    async def test_webhook_outbox_lifecycle(self, tmp_path: Path) -> None:
        from teleclaude.core.db import Db

        test_db = Db(str(tmp_path / "test.db"))
        await test_db.initialize()

        row_id = await test_db.enqueue_webhook("c1", '{"test": true}', "https://example.com", "secret")
        assert row_id > 0

        # Use a future timestamp so it's always after the row's next_attempt_at
        future = "2099-01-01T00:00:00Z"
        rows = await test_db.fetch_webhook_batch(10, future)
        assert len(rows) == 1

        claimed = await test_db.claim_webhook(row_id, future)
        assert claimed is True

        await test_db.mark_webhook_delivered(row_id)

        rows = await test_db.fetch_webhook_batch(10, future)
        assert len(rows) == 0

        await test_db.close()

    @pytest.mark.asyncio
    async def test_webhook_outbox_retry(self, tmp_path: Path) -> None:
        from teleclaude.core.db import Db

        test_db = Db(str(tmp_path / "test.db"))
        await test_db.initialize()

        row_id = await test_db.enqueue_webhook("c1", '{"test": true}', "https://example.com")

        # Use future to ensure we can fetch/claim the newly enqueued row
        fetch_now = "2099-01-01T00:00:00Z"
        claimed = await test_db.claim_webhook(row_id, fetch_now)
        assert claimed is True

        far_future = "2099-06-01T00:00:00Z"
        await test_db.mark_webhook_failed(row_id, "timeout", 1, far_future)

        # Should not be fetchable since next_attempt is far_future and we query with fetch_now
        rows = await test_db.fetch_webhook_batch(10, fetch_now)
        assert len(rows) == 0

        await test_db.close()


# ── Config loading tests ─────────────────────────────────────────────


class TestConfigLoading:
    @pytest.mark.asyncio
    async def test_load_subscription_config(self) -> None:
        from teleclaude.hooks.config import load_hooks_config
        from teleclaude.hooks.registry import ContractRegistry

        registry = ContractRegistry()
        # Mock DB calls since we don't have a real DB in this test
        with patch.object(registry, "register", new_callable=AsyncMock) as mock_register:
            hooks_config = {
                "subscriptions": [
                    {
                        "id": "error-alerts",
                        "contract": {
                            "source": {"match": "agent"},
                            "type": {"match": "error"},
                            "severity": {"match": "critical"},
                        },
                        "target": {
                            "url": "https://alerts.example.com/webhook",
                            "secret": "s3cret",
                        },
                    }
                ],
                "inbound": {},
            }
            await load_hooks_config(hooks_config, registry)

            mock_register.assert_called_once()
            registered_contract = mock_register.call_args[0][0]
            assert registered_contract.id == "error-alerts"
            assert registered_contract.source_criterion is not None
            assert registered_contract.source_criterion.match == "agent"
            assert registered_contract.target.url == "https://alerts.example.com/webhook"
            assert registered_contract.source == "config"

    def test_hooks_config_schema(self) -> None:
        from teleclaude.config.schema import HooksConfig

        cfg = HooksConfig()
        assert cfg.inbound == {}
        assert cfg.subscriptions == []


# ── Bridge tests ─────────────────────────────────────────────────────


class TestEventBusBridge:
    @pytest.mark.asyncio
    async def test_bridge_normalizes_session_event(self) -> None:
        from teleclaude.core.events import SessionLifecycleContext
        from teleclaude.hooks.bridge import EventBusBridge

        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock()
        bridge = EventBusBridge(dispatcher)

        await bridge._handle("session_started", SessionLifecycleContext(session_id="sess-123"))

        dispatcher.dispatch.assert_called_once()
        event = dispatcher.dispatch.call_args[0][0]
        assert event.source == "system"
        assert "session" in event.type
        assert event.properties["session_id"] == "sess-123"

    @pytest.mark.asyncio
    async def test_bridge_normalizes_error_event(self) -> None:
        from teleclaude.core.events import ErrorEventContext
        from teleclaude.hooks.bridge import EventBusBridge

        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock()
        bridge = EventBusBridge(dispatcher)

        await bridge._handle(
            "error",
            ErrorEventContext(session_id="sess-456", message="boom", severity="critical"),
        )

        dispatcher.dispatch.assert_called_once()
        event = dispatcher.dispatch.call_args[0][0]
        assert event.source == "system"
        assert "error" in event.type
        assert event.properties["severity"] == "critical"
