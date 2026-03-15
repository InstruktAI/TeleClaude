from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from teleclaude.core.db import Db
from teleclaude.core.db._sync import (
    _fetch_session_id_sync,
    get_session_field_sync,
    get_session_id_by_field_sync,
    get_session_id_by_tmux_name_sync,
    resolve_session_principal,
)
from teleclaude.core.models import Session, SessionAdapterMetadata

pytestmark = pytest.mark.asyncio


async def test_fetch_session_id_sync_returns_latest_open_match(db: Db) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-old",
        last_input_origin="telegram",
        title="Old",
        session_id="sess-old",
        emit_session_started=False,
    )
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-new",
        last_input_origin="telegram",
        title="New",
        session_id="sess-new",
        emit_session_started=False,
    )
    await db.create_session(
        computer_name="other-mac",
        tmux_session_name="tmux-other",
        last_input_origin="telegram",
        title="Other",
        session_id="sess-other",
        emit_session_started=False,
    )
    await db.update_session("sess-old", last_activity=datetime.now(UTC) - timedelta(hours=1))
    await db.update_session("sess-new", last_activity=datetime.now(UTC) + timedelta(hours=1))

    by_field = get_session_id_by_field_sync(db.db_path, "computer_name", "builder-mac")
    by_tmux = get_session_id_by_tmux_name_sync(db.db_path, "tmux-new")

    assert by_field == "sess-new"
    assert by_tmux == "sess-new"


async def test_sync_helpers_reject_invalid_fields(db: Db) -> None:
    with pytest.raises(ValueError, match="Invalid field"):
        _fetch_session_id_sync(db.db_path, "not_a_field", "value")

    with pytest.raises(ValueError, match="Invalid field"):
        get_session_field_sync(db.db_path, "sess-001", "not_a_field")


async def test_sync_helpers_return_none_when_schema_is_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"

    assert get_session_id_by_tmux_name_sync(str(db_path), "tmux-001") is None
    assert get_session_field_sync(str(db_path), "sess-001", "title") is None


async def test_resolve_session_principal_prefers_inherited_then_human_then_system() -> None:
    inherited = Session(
        session_id="sess-001",
        computer_name="builder-mac",
        tmux_session_name="tmux-001",
        title="Inherited",
        adapter_metadata=SessionAdapterMetadata(),
        principal="human:parent@example.com",
        human_role="member",
    )
    human = Session(
        session_id="sess-002",
        computer_name="builder-mac",
        tmux_session_name="tmux-002",
        title="Human",
        adapter_metadata=SessionAdapterMetadata(),
        human_email="alice@example.com",
        human_role=None,
    )
    system = Session(
        session_id="sess-003",
        computer_name="builder-mac",
        tmux_session_name="tmux-003",
        title="System",
        adapter_metadata=SessionAdapterMetadata(),
        human_email=None,
        human_role="worker",
    )

    assert resolve_session_principal(inherited) == ("human:parent@example.com", "member")
    assert resolve_session_principal(human) == ("human:alice@example.com", "customer")
    assert resolve_session_principal(system) == ("system:sess-003", "worker")
