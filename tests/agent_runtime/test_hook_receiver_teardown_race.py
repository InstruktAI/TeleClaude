"""Functional regression: non-headless hook receiver vs. the session-teardown race.

`terminate_session` marks a row `closing`, kills the tmux pane, then reclaims the
per-session TMPDIR (deleting `teleclaude_identity.json`). The killed pane's agent
can still emit a final `user_prompt_submit` hook after the marker is gone. These
tests drive `receiver_mod.main()` end to end (real TMUX/TMPDIR env, real main-DB
session rows) to pin that the receiver classifies that race as a benign drop
rather than a contract violation, while a genuinely live session still resolves
and a genuinely missing TMPDIR/TMP/TEMP environment still hard-fails.
"""

from __future__ import annotations

import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlmodel import Session as SqlSession
from sqlmodel import select

import teleclaude.hooks.receiver as receiver_mod
from teleclaude import paths as tc_paths
from teleclaude.core import db_models
from teleclaude.core.db import Db
from teleclaude.core.db.connection_factory import get_outbox_db_path
from teleclaude.core.db_models import HookOutbox
from teleclaude.core.events import AgentHookEvents
from teleclaude.hooks.receiver import _session as session_mod

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_NATIVE_SESSION_ID = "native-teardown-race"
_SEEDED_SESSION_ID = "8f7f3c1a-0000-4000-8000-000000000001"


async def _install_main_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the receiver's sync engine at a freshly bootstrapped main DB."""
    main_db_path = tmp_path / "main.db"
    main_db = Db(str(main_db_path))
    await main_db.initialize()
    monkeypatch.setattr(tc_paths, "MAIN_DB_PATH", main_db_path)
    monkeypatch.setattr(session_mod, "_sync_engine", None)


def _seed_session(*, session_id: str, native_session_id: str, lifecycle_status: str, closed: bool) -> None:
    engine = session_mod._create_sync_engine()
    with SqlSession(engine) as db_session:
        db_session.add(
            db_models.Session(
                session_id=session_id,
                computer_name="local",
                native_session_id=native_session_id,
                active_agent="claude",
                lifecycle_status=lifecycle_status,
                created_at=datetime.now(UTC),
                closed_at=datetime.now(UTC) if closed else None,
            )
        )
        db_session.commit()


def _run_receiver(
    monkeypatch: pytest.MonkeyPatch,
    *,
    outbox_db: str,
    native_session_id: str,
    tmux_tmpdir: Path | None,
) -> None:
    """Invoke the receiver for a non-headless UserPromptSubmit, no session mocking."""
    monkeypatch.setattr(receiver_mod, "_get_default_outbox_db", lambda: outbox_db)
    monkeypatch.setenv("TMUX", "/tmp/tmux-0/default,123,0")
    monkeypatch.delenv("TMP", raising=False)
    monkeypatch.delenv("TEMP", raising=False)
    if tmux_tmpdir is not None:
        monkeypatch.setenv("TMPDIR", str(tmux_tmpdir))
    else:
        monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.setattr(sys, "argv", ["receiver", "--agent", "claude", "UserPromptSubmit"])
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"prompt": "hello from a dying pane", "session_id": native_session_id})),
    )
    receiver_mod.main()


def _read_outbox_rows(outbox_db: str) -> list[HookOutbox]:
    with receiver_mod.get_outbox_session(outbox_db) as session:
        return list(session.exec(select(HookOutbox).order_by(HookOutbox.id)).all())


async def test_teardown_race_no_session_row_drops_quietly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Absent identity marker + no matching DB session -> quiet drop, no outbox row."""
    await _install_main_db(monkeypatch, tmp_path)
    outbox_db = str(get_outbox_db_path(tmp_path))
    empty_tmpdir = tmp_path / "hook-tmp-no-marker"
    empty_tmpdir.mkdir()

    with pytest.raises(SystemExit) as exc_info:
        _run_receiver(monkeypatch, outbox_db=outbox_db, native_session_id=_NATIVE_SESSION_ID, tmux_tmpdir=empty_tmpdir)
    assert exc_info.value.code == 0
    assert _read_outbox_rows(outbox_db) == []


async def test_teardown_race_closing_session_drops_quietly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Absent identity marker + DB row `lifecycle_status='closing'` -> quiet drop.

    This is the exact diagnosed teardown-window state: `terminate_session` sets
    `closing` before killing the pane and deleting the TMPDIR, so `closed_at` is
    still None when the late hook arrives.
    """
    await _install_main_db(monkeypatch, tmp_path)
    _seed_session(
        session_id=_SEEDED_SESSION_ID,
        native_session_id=_NATIVE_SESSION_ID,
        lifecycle_status="closing",
        closed=False,
    )
    outbox_db = str(get_outbox_db_path(tmp_path))
    empty_tmpdir = tmp_path / "hook-tmp-no-marker"
    empty_tmpdir.mkdir()

    with pytest.raises(SystemExit) as exc_info:
        _run_receiver(monkeypatch, outbox_db=outbox_db, native_session_id=_NATIVE_SESSION_ID, tmux_tmpdir=empty_tmpdir)
    assert exc_info.value.code == 0
    assert _read_outbox_rows(outbox_db) == []


async def test_teardown_race_live_session_is_attributed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Absent identity marker + a genuinely live DB row -> the hook is attributed."""
    await _install_main_db(monkeypatch, tmp_path)
    _seed_session(
        session_id=_SEEDED_SESSION_ID,
        native_session_id=_NATIVE_SESSION_ID,
        lifecycle_status="active",
        closed=False,
    )
    outbox_db = str(get_outbox_db_path(tmp_path))
    empty_tmpdir = tmp_path / "hook-tmp-no-marker"
    empty_tmpdir.mkdir()

    _run_receiver(monkeypatch, outbox_db=outbox_db, native_session_id=_NATIVE_SESSION_ID, tmux_tmpdir=empty_tmpdir)

    rows = [row for row in _read_outbox_rows(outbox_db) if row.event_type == AgentHookEvents.USER_PROMPT_SUBMIT]
    assert len(rows) == 1
    assert rows[0].session_id == _SEEDED_SESSION_ID


async def test_missing_tmpdir_env_is_still_a_contract_violation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A completely missing TMPDIR/TMP/TEMP env remains a hard contract breach."""
    await _install_main_db(monkeypatch, tmp_path)
    outbox_db = str(get_outbox_db_path(tmp_path))

    with pytest.raises(SystemExit) as exc_info:
        _run_receiver(monkeypatch, outbox_db=outbox_db, native_session_id=_NATIVE_SESSION_ID, tmux_tmpdir=None)
    assert exc_info.value.code == 1
    assert _read_outbox_rows(outbox_db) == []
