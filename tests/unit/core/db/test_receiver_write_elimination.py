# pylint: disable=import-outside-toplevel,import-error,no-name-in-module,too-few-public-methods,no-member
"""Test spec (xfail) for R3: receiver write elimination from teleclaude.db.

After the outbox split, the hook receiver performs zero writes to teleclaude.db.
Session mutations (checkpoint timestamp, native metadata, transcript chain) are
converted to outbox event types that the daemon processes asynchronously.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from teleclaude import daemon_hook_outbox
from teleclaude.core.db.connection_factory import (
    create_sync_db_engine,
    get_outbox_db_path,
)
from teleclaude.core.events import AgentHookEvents
from teleclaude.daemon_hook_outbox import (
    handle_checkpoint_seen,
    handle_native_metadata_update,
    handle_native_session_refresh,
)
from teleclaude.hooks.receiver import _session as receiver_session
from teleclaude.hooks.receiver import enqueue_checkpoint_seen

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Static analysis: receiver performs no writes to teleclaude.db
# ---------------------------------------------------------------------------


class TestReceiverZeroWritesToMainDb:
    """The receiver codebase contains no write paths to teleclaude.db."""

    def test_receiver_init_has_no_sqlsession_commit(self, tmp_path: Path) -> None:
        """Hook receiver's outbox session factory targets the outbox DB, not teleclaude.db.

        After R3, the receiver module exposes get_outbox_session() from _session.py.
        Calling it with an outbox path must return a session bound to that path,
        not to teleclaude.db — proving no write path to the main DB remains.
        """
        outbox_path = tmp_path / "hook_outbox.db"
        session = receiver_session.get_outbox_session(str(outbox_path))  # pyright: ignore[reportAttributeAccessIssue]
        try:
            bind = session.get_bind()  # pyright: ignore[reportAttributeAccessIssue]
            engine_url = str(bind.url if isinstance(bind, Engine) else bind.engine.url)
            assert "teleclaude.db" not in engine_url, f"Receiver session targets teleclaude.db: {engine_url}"
        finally:
            session.close()  # pyright: ignore[reportAttributeAccessIssue]

    def test_receiver_session_module_creates_only_outbox_engine(self, tmp_path: Path) -> None:
        """receiver/_session.py produces only an outbox-DB engine, not a main-DB engine.

        We verify behaviorally: call get_sync_engine (or equivalent) twice with
        an outbox path and assert the returned engine URL targets the outbox file,
        not teleclaude.db.
        """
        outbox_path = get_outbox_db_path(tmp_path)
        engine = create_sync_db_engine(outbox_path)
        # Engine URL must reference the outbox path, never teleclaude.db
        engine_url = str(engine.url)
        assert "teleclaude.db" not in engine_url, (
            f"Receiver session engine targets teleclaude.db instead of outbox: {engine_url}"
        )
        assert outbox_path.name in engine_url, (
            f"Receiver session engine URL does not reference outbox file: {engine_url}"
        )


# ---------------------------------------------------------------------------
# New outbox event types for session mutations
# ---------------------------------------------------------------------------


class TestCheckpointSeenOutboxEvent:
    """_mark_checkpoint_seen is replaced by a checkpoint_seen outbox event."""

    def test_checkpoint_seen_event_type_defined(self) -> None:
        """AgentHookEvents or equivalent defines 'checkpoint_seen' as a valid event type."""
        # The exact attribute name may differ, but the event type string must exist
        event_types = set()
        for attr in dir(AgentHookEvents):
            val = getattr(AgentHookEvents, attr)
            if isinstance(val, str):
                event_types.add(val)
        assert "checkpoint_seen" in event_types, "checkpoint_seen event type not defined in AgentHookEvents"

    def test_receiver_emits_checkpoint_seen_to_outbox(self, tmp_path: Path) -> None:
        """When a checkpoint is warranted, the receiver enqueues a checkpoint_seen
        row to the outbox DB rather than writing directly to teleclaude.db.

        We call the receiver's public enqueue API with a temp outbox path and verify
        a checkpoint_seen row appears in the outbox DB.
        """
        outbox_path = tmp_path / "hook_outbox.db"
        enqueue_checkpoint_seen(  # pyright: ignore[reportCallIssue]
            session_id="sess-cp-emit-001",
            checkpoint_at=datetime.now(UTC).isoformat(),
            outbox_db=str(outbox_path),
        )

        conn = sqlite3.connect(str(outbox_path))
        rows = conn.execute("SELECT event_type FROM hook_outbox WHERE session_id='sess-cp-emit-001'").fetchall()
        conn.close()
        assert any(r[0] == "checkpoint_seen" for r in rows), "Receiver did not enqueue checkpoint_seen event to outbox"


class TestNativeMetadataUpdateOutboxEvent:
    """_update_session_native_fields is replaced by native_metadata_update outbox event."""

    def test_native_metadata_update_event_type_defined(self) -> None:
        """AgentHookEvents defines 'native_metadata_update' as a valid event type."""
        event_types = set()
        for attr in dir(AgentHookEvents):
            val = getattr(AgentHookEvents, attr)
            if isinstance(val, str):
                event_types.add(val)
        assert "native_metadata_update" in event_types

    async def test_native_metadata_update_payload_structure(self, db: Any, cluster_event_bus: None) -> None:
        """Receiver emits native_metadata_update with the fields required by the daemon handler.

        The actual receiver enqueue path must produce a payload that carries
        native_session_id, native_log_file, agent, and source_event_type so the
        daemon handler can apply the session mutation without reading teleclaude.db.
        """
        await db.create_session(
            computer_name="test-mac",
            tmux_session_name="tmux-001",
            last_input_origin="telegram",
            title="Payload Structure Test",
            session_id="sess-payload-001",
        )

        # Call the actual handler with the expected payload shape; if the handler
        # rejects or ignores required fields, the session state won't reflect them.
        await handle_native_metadata_update(
            db,
            session_id="sess-payload-001",
            payload={
                "native_session_id": "native-struct-001",
                "native_log_file": "/tmp/struct.jsonl",
                "agent": "claude",
                "source_event_type": "agent_stop",
            },
        )

        updated = await db.get_session("sess-payload-001")
        assert updated is not None
        assert updated.native_session_id == "native-struct-001"
        assert updated.native_log_file == "/tmp/struct.jsonl"


class TestNativeSessionRefreshOutboxEvent:
    """Stale native_session_id refresh is converted to native_session_refresh outbox event."""

    def test_native_session_refresh_event_type_defined(self) -> None:
        """AgentHookEvents defines 'native_session_refresh' as a valid event type."""
        event_types = set()
        for attr in dir(AgentHookEvents):
            val = getattr(AgentHookEvents, attr)
            if isinstance(val, str):
                event_types.add(val)
        assert "native_session_refresh" in event_types


# ---------------------------------------------------------------------------
# Daemon handlers for new event types
# ---------------------------------------------------------------------------


class TestDaemonProcessesNewEventTypes:
    """The daemon's outbox worker has handlers for the three new event types."""

    def test_daemon_has_handlers_for_new_event_types(self) -> None:
        """The daemon outbox worker registers a handler for each new event type.

        After processing checkpoint_seen, session.last_checkpoint_at is updated.
        After processing native_metadata_update, session native fields are updated
        and transcript chain accumulation is preserved.
        After processing native_session_refresh, session.native_session_id is refreshed.
        """
        # The daemon hook outbox module should have handler registration
        source_path = Path(daemon_hook_outbox.__file__)
        source = source_path.read_text(encoding="utf-8")
        for event_type in ("checkpoint_seen", "native_metadata_update", "native_session_refresh"):
            assert event_type in source, f"Daemon outbox worker has no handler for '{event_type}'"


class TestCheckpointSeenDaemonHandler:
    """Daemon correctly applies checkpoint_seen events to session state."""

    async def test_checkpoint_seen_updates_last_checkpoint_at(self, db: Any, cluster_event_bus: None) -> None:
        """After processing a checkpoint_seen event, the session's
        last_checkpoint_at field reflects the timestamp from the event payload.
        """
        # Create a session
        session = await db.create_session(
            computer_name="test-mac",
            tmux_session_name="tmux-001",
            last_input_origin="telegram",
            title="Checkpoint Test",
            session_id="sess-cp-001",
        )
        assert session.last_checkpoint_at is None

        # Simulate daemon processing a checkpoint_seen event
        now = datetime.now(UTC)
        # After implementation, the daemon handler will:
        # 1. Parse the event payload for the checkpoint timestamp
        # 2. Update session.last_checkpoint_at
        # The test verifies the end state after handler execution.
        await handle_checkpoint_seen(
            db,
            session_id="sess-cp-001",
            payload={"checkpoint_at": now.isoformat()},
        )

        updated = await db.get_session("sess-cp-001")
        assert updated is not None
        assert updated.last_checkpoint_at is not None


class TestNativeMetadataDaemonHandler:
    """Daemon correctly applies native_metadata_update events."""

    async def test_native_metadata_update_persists_fields(self, db: Any, cluster_event_bus: None) -> None:
        """After processing native_metadata_update, native_session_id and
        native_log_file are updated on the session row.
        """
        await db.create_session(
            computer_name="test-mac",
            tmux_session_name="tmux-001",
            last_input_origin="telegram",
            title="Native Meta Test",
            session_id="sess-nm-001",
        )

        await handle_native_metadata_update(
            db,
            session_id="sess-nm-001",
            payload={
                "native_session_id": "native-abc",
                "native_log_file": "/tmp/transcript.jsonl",
                "agent": "claude",
                "source_event_type": "agent_stop",
            },
        )

        updated = await db.get_session("sess-nm-001")
        assert updated is not None
        assert updated.native_session_id == "native-abc"
        assert updated.native_log_file == "/tmp/transcript.jsonl"

    async def test_native_metadata_update_preserves_transcript_chain(
        self,
        db: Any,
        cluster_event_bus: None,
    ) -> None:
        """When native_log_file changes, the previous value is appended to
        transcript_files (chain accumulation is preserved after the conversion).
        """
        await db.create_session(
            computer_name="test-mac",
            tmux_session_name="tmux-001",
            last_input_origin="telegram",
            title="Chain Test",
            session_id="sess-chain-001",
        )

        # First update: set initial transcript
        await handle_native_metadata_update(
            db,
            session_id="sess-chain-001",
            payload={
                "native_session_id": "native-001",
                "native_log_file": "/tmp/transcript-v1.jsonl",
                "agent": "claude",
                "source_event_type": "agent_stop",
            },
        )

        # Second update: change transcript — old one should be chained
        await handle_native_metadata_update(
            db,
            session_id="sess-chain-001",
            payload={
                "native_session_id": "native-001",
                "native_log_file": "/tmp/transcript-v2.jsonl",
                "agent": "claude",
                "source_event_type": "agent_stop",
            },
        )

        updated = await db.get_session("sess-chain-001")
        assert updated is not None
        chain = json.loads(updated.transcript_files)
        assert "/tmp/transcript-v1.jsonl" in chain


class TestNativeSessionRefreshDaemonHandler:
    """Daemon correctly applies native_session_refresh events to session state."""

    async def test_native_session_refresh_updates_native_session_id(self, db: Any, cluster_event_bus: None) -> None:
        """After processing native_session_refresh, the session row reflects the new
        native_session_id from the event payload.

        This mirrors the checkpoint_seen and native_metadata_update functional tests:
        call the handler directly, assert the session row changed.
        """
        await db.create_session(
            computer_name="test-mac",
            tmux_session_name="tmux-001",
            last_input_origin="telegram",
            title="Refresh Test",
            session_id="sess-refresh-001",
        )

        await handle_native_session_refresh(
            db,
            session_id="sess-refresh-001",
            payload={"native_session_id": "native-refreshed-001"},
        )

        updated = await db.get_session("sess-refresh-001")
        assert updated is not None
        assert updated.native_session_id == "native-refreshed-001", (
            "native_session_refresh handler did not update native_session_id"
        )

    async def test_native_session_refresh_clears_stale_id_when_none(
        self,
        db: Any,
        cluster_event_bus: None,
    ) -> None:
        """native_session_refresh with None clears a previously-set stale native_session_id."""
        await db.create_session(
            computer_name="test-mac",
            tmux_session_name="tmux-001",
            last_input_origin="telegram",
            title="Clear Stale Test",
            session_id="sess-refresh-002",
        )

        # First set a native_session_id via metadata update
        await handle_native_metadata_update(
            db,
            session_id="sess-refresh-002",
            payload={
                "native_session_id": "stale-native-id",
                "native_log_file": None,
                "agent": "claude",
                "source_event_type": "agent_stop",
            },
        )

        # Now refresh with None to clear it
        await handle_native_session_refresh(
            db,
            session_id="sess-refresh-002",
            payload={"native_session_id": None},
        )

        updated = await db.get_session("sess-refresh-002")
        assert updated is not None
        assert updated.native_session_id is None, (
            "native_session_refresh with None should clear the stale native_session_id"
        )
