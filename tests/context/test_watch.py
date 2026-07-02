"""Functional coverage for the docs watcher sync boundary."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from subprocess import CompletedProcess
from typing import cast

import pytest
from watchdog.events import FileModifiedEvent

from teleclaude.cli import telec as telec_cli
from teleclaude.cli import watch as watch_mod
from teleclaude.cli.watch import SmartWatcher
from teleclaude.core.models import JsonDict
from teleclaude.events import build_default_catalog
from teleclaude.events.cartridges.correlation import CorrelationCartridge
from teleclaude.events.cartridges.notification import NotificationProjectorCartridge
from teleclaude.events.db import EventDB
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude.events.pipeline import PipelineContext
from teleclaude.events.producer import EventProducer

pytestmark = pytest.mark.functional

_DOCS_WATCHER_SYNC_FAILED_EVENT = "system.docs_watcher.sync_failed"


@dataclass(frozen=True)
class _CapturedEmit:
    event: str
    entity: str
    payload: JsonDict


def _watcher_with_counted_sync(monkeypatch: pytest.MonkeyPatch, project_root: Path) -> tuple[SmartWatcher, list[Path]]:
    sync_calls: list[Path] = []

    def fake_sync(self: SmartWatcher) -> None:
        sync_calls.append(self.project_root)

    monkeypatch.setattr(SmartWatcher, "_sync", fake_sync)
    watcher = SmartWatcher(project_root)
    return watcher, sync_calls


def test_domain_baseline_bundle_change_does_not_trigger_docs_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generated domain-baseline bundle writes are ignored at the watcher input boundary."""
    watcher, sync_calls = _watcher_with_counted_sync(monkeypatch, tmp_path)

    watcher.on_any_event(FileModifiedEvent(str(tmp_path / "docs/global/erp/domain-baseline-bundle.md")))

    assert len(sync_calls) == 1


def test_deployed_domain_baseline_bundle_change_does_not_trigger_docs_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generated deployed-form bundle writes are ignored at the watcher input boundary."""
    watcher, sync_calls = _watcher_with_counted_sync(monkeypatch, tmp_path)

    watcher.on_any_event(FileModifiedEvent(str(tmp_path / "docs/software-development/domain-baseline-bundle.md")))

    assert len(sync_calls) == 1


def test_docs_content_change_triggers_docs_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real docs content change still triggers sync through the watcher input boundary."""
    watcher, sync_calls = _watcher_with_counted_sync(monkeypatch, tmp_path)

    watcher.on_any_event(FileModifiedEvent(str(tmp_path / "docs/global/erp/some-snippet.md")))

    assert len(sync_calls) == 2


def test_default_catalog_registers_docs_watcher_failure_event() -> None:
    """The built-in event catalog includes the docs watcher failure event."""
    catalog = build_default_catalog()
    schema = catalog.get(_DOCS_WATCHER_SYNC_FAILED_EVENT)
    degraded_schema = catalog.get("system.entity.degraded")

    assert schema is not None
    assert degraded_schema is not None
    assert degraded_schema.lifecycle is not None
    assert schema.default_level is EventLevel.WORKFLOW
    assert schema.default_visibility is EventVisibility.LOCAL
    assert schema.domain == degraded_schema.domain
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True
    assert schema.lifecycle.updates is True
    assert schema.lifecycle.group_key == degraded_schema.lifecycle.group_key
    assert set(schema.lifecycle.meaningful_fields) == {"reason", "returncode", "trigger_count"}
    assert schema.actionable is True


def test_events_list_surfaces_docs_watcher_failure_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """The public events-list boundary surfaces the docs watcher failure event."""
    out = StringIO()
    monkeypatch.setattr(sys, "argv", ["telec", "events", "list", "--domain", "system"])
    monkeypatch.setattr("sys.stdout", out)

    telec_cli.main()

    event_types = {line[:55].strip() for line in out.getvalue().splitlines()[2:]}
    assert _DOCS_WATCHER_SYNC_FAILED_EVENT in event_types


def test_docs_watcher_emits_failure_event_on_sync_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed sync emits a docs-watcher failure event at the transport boundary."""
    emitted: list[_CapturedEmit] = []
    subprocess_results: Iterator[CompletedProcess[str]] = iter(
        [
            CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            CompletedProcess(args=[], returncode=1, stdout="", stderr="sync exploded"),
        ]
    )

    async def fake_emit_event(event: str, **kwargs: object) -> str:
        emitted.append(
            _CapturedEmit(event=event, entity=cast(str, kwargs["entity"]), payload=cast(JsonDict, kwargs["payload"]))
        )
        return "1-0"

    monkeypatch.setattr(watch_mod.subprocess, "run", lambda *args, **kwargs: next(subprocess_results))
    monkeypatch.setattr(watch_mod, "ensure_event_producer", lambda: object(), raising=False)
    monkeypatch.setattr(watch_mod, "emit_event", fake_emit_event, raising=False)
    watcher = SmartWatcher(tmp_path)

    watcher.on_any_event(FileModifiedEvent(str(tmp_path / "docs/global/erp/some-snippet.md")))

    assert len(emitted) == 1
    captured = emitted[0]
    assert captured.event == watch_mod._DOCS_WATCHER_SYNC_FAILED_EVENT
    assert captured.entity == str(tmp_path.resolve())
    payload = captured.payload
    assert payload["entity"] == str(tmp_path.resolve())
    assert payload["reason"] == watch_mod._SYNC_FAILED_REASON
    assert payload["returncode"] == 1


def test_docs_watcher_emits_one_loop_signature_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated sync triggers within the loop window emit one loop-signature event."""
    emitted: list[_CapturedEmit] = []
    current_time = 100.0

    def fake_time() -> float:
        nonlocal current_time
        current_time += 1.0
        return current_time

    async def fake_emit_event(event: str, **kwargs: object) -> str:
        emitted.append(
            _CapturedEmit(event=event, entity=cast(str, kwargs["entity"]), payload=cast(JsonDict, kwargs["payload"]))
        )
        return "1-0"

    monkeypatch.setattr(SmartWatcher, "_sync", lambda self: None)
    monkeypatch.setattr(watch_mod.time, "time", fake_time)
    monkeypatch.setattr(watch_mod, "ensure_event_producer", lambda: object(), raising=False)
    monkeypatch.setattr(watch_mod, "emit_event", fake_emit_event, raising=False)
    watcher = SmartWatcher(tmp_path, debounce_seconds=0.0)

    for index in range(watch_mod._LOOP_TRIGGER_THRESHOLD):
        watcher.on_any_event(FileModifiedEvent(str(tmp_path / f"docs/global/erp/snippet-{index}.md")))

    assert len(emitted) == 1
    captured = emitted[0]
    assert captured.event == watch_mod._DOCS_WATCHER_SYNC_FAILED_EVENT
    payload = captured.payload
    assert payload["reason"] == watch_mod._LOOP_DETECTED_REASON
    assert payload["trigger_count"] == watch_mod._LOOP_TRIGGER_THRESHOLD
    assert payload["window_seconds"] == watch_mod._LOOP_WINDOW_S


def test_docs_watcher_emit_failure_does_not_escape_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Event transport failures do not propagate out of the watcher boundary."""

    async def fake_emit_event(event: str, **kwargs: object) -> str:
        raise RuntimeError("transport unavailable")

    monkeypatch.setattr(
        watch_mod.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcess(args=[], returncode=1, stdout="", stderr="sync exploded"),
    )
    monkeypatch.setattr(watch_mod, "ensure_event_producer", lambda: object(), raising=False)
    monkeypatch.setattr(watch_mod, "emit_event", fake_emit_event, raising=False)
    watcher = SmartWatcher(tmp_path)

    watcher.on_any_event(FileModifiedEvent(str(tmp_path / "docs/global/erp/some-snippet.md")))


def _docs_watcher_event(project_root: Path, reason: str) -> EventEnvelope:
    schema = build_default_catalog().get(_DOCS_WATCHER_SYNC_FAILED_EVENT)
    assert schema is not None
    return EventEnvelope(
        event=schema.event_type,
        source="docs-watch",
        level=schema.default_level,
        domain=schema.domain,
        visibility=schema.default_visibility,
        entity=str(project_root),
        payload={"entity": str(project_root), "reason": reason, "returncode": 1},
    )


@pytest.mark.asyncio
async def test_docs_watcher_notifications_group_by_payload_entity(tmp_path: Path) -> None:
    """Docs-watcher failures for one root update one notification; different roots do not collide."""
    db = EventDB(tmp_path / "events.sqlite")
    await db.initialize()
    try:
        context = PipelineContext(catalog=build_default_catalog(), db=db)
        projector = NotificationProjectorCartridge()
        first_root = tmp_path / "first"
        second_root = tmp_path / "second"
        await projector.process(_docs_watcher_event(first_root, watch_mod._SYNC_FAILED_REASON), context)
        await projector.process(_docs_watcher_event(first_root, watch_mod._SYNC_FAILED_REASON), context)

        same_root_rows = await db.list_notifications(limit=10)

        await projector.process(_docs_watcher_event(second_root, watch_mod._SYNC_FAILED_REASON), context)
        different_root_rows = await db.list_notifications(limit=10)
    finally:
        await db.close()

    assert len(same_root_rows) == 1
    assert len(different_root_rows) == 2


class _CapturingProducer:
    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope] = []

    async def emit(self, envelope: EventEnvelope) -> str:
        self.envelopes.append(envelope)
        return "1-0"


@pytest.mark.asyncio
async def test_docs_watcher_failures_feed_entity_degradation(tmp_path: Path) -> None:
    """Repeated docs-watcher failures feed entity degradation through the correlation boundary."""
    db = EventDB(tmp_path / "events.sqlite")
    await db.initialize()
    producer = _CapturingProducer()
    try:
        context = PipelineContext(catalog=build_default_catalog(), db=db, producer=cast(EventProducer, producer))
        cartridge = CorrelationCartridge()
        project_root = tmp_path / "project"

        for _ in range(context.correlation_config.entity_failure_threshold):
            await cartridge.process(_docs_watcher_event(project_root, watch_mod._SYNC_FAILED_REASON), context)
    finally:
        await db.close()

    degraded_schema = build_default_catalog().get("system.entity.degraded")
    assert degraded_schema is not None
    assert len(producer.envelopes) == 1
    assert producer.envelopes[0].event == degraded_schema.event_type
    assert producer.envelopes[0].payload["entity"] == str(project_root)
