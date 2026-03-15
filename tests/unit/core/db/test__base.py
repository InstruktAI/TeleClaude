from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest

from teleclaude.constants import DB_IN_MEMORY
from teleclaude.core import db_models
from teleclaude.core.db._base import DbBase
from teleclaude.core.models import SessionAdapterMetadata, SessionMetadata, TelegramAdapterMetadata


def test_serialize_helpers_preserve_supported_input_shapes() -> None:
    metadata = SessionMetadata(system_role="builder", job="chartest")
    adapter = SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=12, output_suppressed=True))

    assert DbBase._serialize_adapter_metadata(None) is None
    assert DbBase._serialize_adapter_metadata('{"telegram":{"topic_id":12}}') == '{"telegram":{"topic_id":12}}'
    assert json.loads(DbBase._serialize_adapter_metadata({"telegram": {"topic_id": 12}}) or "{}") == {
        "telegram": {"topic_id": 12}
    }
    assert json.loads(DbBase._serialize_adapter_metadata(adapter) or "{}") == {
        "telegram": {"topic_id": 12, "output_suppressed": True, "char_offset": 0, "badge_sent": False}
    }
    assert json.loads(DbBase._serialize_session_metadata(metadata) or "{}") == {
        "system_role": "builder",
        "job": "chartest",
        "human_email": None,
        "human_role": None,
        "principal": None,
    }


def test_to_core_session_filters_unknown_metadata_and_normalizes_flags() -> None:
    row = db_models.Session(
        session_id="sess-001",
        computer_name="builder-mac",
        tmux_session_name="tmux-001",
        last_input_origin="telegram",
        title=None,
        adapter_metadata=json.dumps({"telegram": {"topic_id": "42", "output_suppressed": True}}),
        session_metadata=json.dumps({"system_role": "reviewer", "job": "chartest", "ignored": "value"}),
        initiated_by_ai=1,
        notification_sent=0,
        tui_capture_started=1,
        turn_triggered_by_linked_output=True,
        char_offset="7",
        lifecycle_status=None,
        visibility=None,
        created_at="2025-01-02T03:04:05Z",
        last_activity=datetime(2025, 1, 2, 3, 5, 0),
    )

    session = DbBase._to_core_session(row)

    assert session.title == ""
    assert session.adapter_metadata.get_ui().get_telegram().topic_id == 42
    assert session.session_metadata == SessionMetadata(system_role="reviewer", job="chartest")
    assert session.initiated_by_ai is True
    assert session.notification_sent is False
    assert session.tui_capture_started is True
    assert session.turn_triggered_by_linked_output is True
    assert session.char_offset == 7
    assert session.lifecycle_status == "active"
    assert session.visibility is None
    assert session.created_at == datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert session.last_activity == datetime(2025, 1, 2, 3, 5, 0, tzinfo=UTC)


def test_session_requires_initialize_before_opening_runtime_session() -> None:
    db = DbBase("unused.db")

    with pytest.raises(RuntimeError, match="Database not initialized"):
        db._session()


@pytest.mark.asyncio
async def test_initialize_in_memory_normalizes_adapter_metadata_and_cleans_up_temp_file() -> None:
    db = DbBase(DB_IN_MEMORY)
    await db.initialize()
    assert db.is_initialized() is True
    assert db._temp_db_path is not None

    async with db._session() as session:
        session.add(
            db_models.Session(
                session_id="sess-001",
                computer_name="builder-mac",
                tmux_session_name="tmux-001",
                last_input_origin="telegram",
                title="Example",
                adapter_metadata=json.dumps({"telegram": {"topic_id": "9"}}),
            )
        )
        await session.commit()

    await db._normalize_adapter_metadata()

    async with db._session() as session:
        row = await session.get(db_models.Session, "sess-001")

    assert row is not None
    assert json.loads(row.adapter_metadata or "{}") == {"telegram": {"topic_id": 9}}

    temp_db_path = db._temp_db_path
    await db.wal_checkpoint()
    await db.close()

    assert temp_db_path is not None
    assert os.path.exists(temp_db_path) is False
