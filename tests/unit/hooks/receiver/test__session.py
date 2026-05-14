"""Characterization tests for teleclaude.hooks.receiver._session."""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

import teleclaude.hooks.receiver._session as session_module
import teleclaude.paths as tc_paths


class _SelectStub:
    def where(self, *_args: object, **_kwargs: object) -> _SelectStub:
        return self

    def order_by(self, *_args: object, **_kwargs: object) -> _SelectStub:
        return self

    def limit(self, *_args: object, **_kwargs: object) -> _SelectStub:
        return self


class _SqlSessionStub:
    def __init__(self, *, row: object | None = None, first: object | None = None) -> None:
        self.row = row
        self.first_value = first
        self.added: list[object] = []
        self.committed = False

    def __enter__(self) -> _SqlSessionStub:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def get(self, _model: object, _session_id: str) -> object | None:
        return self.row

    def add(self, row: object) -> None:
        self.added.append(row)

    def commit(self) -> None:
        self.committed = True

    def exec(self, _statement: object) -> SimpleNamespace:
        return SimpleNamespace(first=lambda: self.first_value)


class _SessionMapSqlSessionStub:
    def __init__(self, rows: Mapping[str, object]) -> None:
        self.rows = rows

    def __enter__(self) -> _SessionMapSqlSessionStub:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def get(self, _model: object, session_id: str) -> object | None:
        return self.rows.get(session_id)


def _install_sqlmodel_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    row: object | None = None,
    first: object | None = None,
) -> _SqlSessionStub:
    session_stub = _SqlSessionStub(row=row, first=first)
    module = types.ModuleType("sqlmodel")

    def _session_factory(_engine: object) -> _SqlSessionStub:
        return session_stub

    def _select_factory(_model: object) -> _SelectStub:
        return _SelectStub()

    def _engine_factory() -> object:
        return object()

    module.Session = _session_factory
    module.select = _select_factory
    monkeypatch.setitem(sys.modules, "sqlmodel", module)
    monkeypatch.setattr(session_module, "_create_sync_engine", _engine_factory)
    # Patch the directly-imported SqlSession binding in the module
    monkeypatch.setattr(session_module, "SqlSession", _session_factory)
    return session_stub


class TestMemoryAndSessionMap:
    @pytest.mark.unit
    def test_get_memory_context_returns_generated_context_and_empty_string_on_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _generate_context(project_name: str, db_path: str, identity_key: str | None = None) -> str:
            return f"{project_name}|{db_path}|{identity_key}"

        def _raise_runtime_error(*_args: object, **_kwargs: object) -> str:
            raise RuntimeError("boom")

        monkeypatch.setattr(
            session_module,
            "generate_context_sync",
            _generate_context,
        )
        monkeypatch.setattr(tc_paths, "MAIN_DB_PATH", Path("/tmp/db.sqlite"))

        assert session_module._get_memory_context("teleclaude", "user-1") == "teleclaude|/tmp/db.sqlite|user-1"

        monkeypatch.setattr(
            session_module,
            "generate_context_sync",
            _raise_runtime_error,
        )

        assert session_module._get_memory_context("teleclaude", "user-1") == ""

    @pytest.mark.unit
    def test_persist_session_map_round_trips_through_cached_lookup(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        session_map_path = tmp_path / "session-map.json"
        monkeypatch.setattr(session_module, "_get_session_map_path", lambda: session_map_path)

        session_module._persist_session_map("claude", "native-1", "session-1")

        assert session_module._load_session_map(session_map_path) == {"claude:native-1": "session-1"}
        assert session_module._get_cached_session_id("claude", "native-1") == "session-1"

    @pytest.mark.unit
    def test_prune_session_map_keeps_only_db_truth_mappings(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        agent = "claude"
        other_agent = "gemini"
        kept_native = "native-kept"
        current_native = "native-current"
        missing_native = "native-missing"
        closed_native = "native-closed"
        wrong_agent_native = "native-wrong-agent"
        stale_native = "native-stale"
        kept_session = "session-kept"
        current_session = "session-current"
        missing_session = "session-missing"
        closed_session = "session-closed"
        wrong_agent_session = "session-wrong-agent"
        session_map_path = tmp_path / "session-map.json"
        session_map_path.write_text(
            json.dumps(
                {
                    session_module._session_map_key(agent, kept_native): kept_session,
                    session_module._session_map_key(agent, missing_native): missing_session,
                    session_module._session_map_key(agent, closed_native): closed_session,
                    session_module._session_map_key(other_agent, wrong_agent_native): wrong_agent_session,
                    session_module._session_map_key(agent, stale_native): current_session,
                    session_module._session_map_key(agent, current_native): current_session,
                }
            ),
            encoding="utf-8",
        )
        rows = {
            kept_session: SimpleNamespace(
                closed_at=None,
                lifecycle_status="active",
                active_agent=agent,
                native_session_id=kept_native,
            ),
            closed_session: SimpleNamespace(
                closed_at="2026-01-01T00:00:00+00:00",
                lifecycle_status="closed",
                active_agent=agent,
                native_session_id=closed_native,
            ),
            wrong_agent_session: SimpleNamespace(
                closed_at=None,
                lifecycle_status="active",
                active_agent=agent,
                native_session_id=wrong_agent_native,
            ),
            current_session: SimpleNamespace(
                closed_at=None,
                lifecycle_status="active",
                active_agent=agent,
                native_session_id=current_native,
            ),
        }
        sql_session = _SessionMapSqlSessionStub(rows)
        monkeypatch.setattr(session_module, "_get_session_map_path", lambda: session_map_path)
        monkeypatch.setattr(
            session_module,
            "_get_sqlmodel_module",
            lambda: SimpleNamespace(Session=lambda _engine: sql_session),
        )
        monkeypatch.setattr(session_module, "_create_sync_engine", lambda: object())

        removed = session_module.prune_session_map()

        assert removed == 4
        assert session_module._load_session_map(session_map_path) == {
            session_module._session_map_key(agent, kept_native): kept_session,
            session_module._session_map_key(agent, current_native): current_session,
        }


class TestTmuxContractResolution:
    @pytest.mark.unit
    def test_tmux_contract_reads_the_marker_file_and_uses_tmpdir_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        identity_file = tmp_path / "teleclaude_identity.json"
        identity_file.write_text(json.dumps({"session_id": "session-1"}), encoding="utf-8")
        monkeypatch.setenv("TMPDIR", str(tmp_path))

        assert session_module._get_tmux_contract_tmpdir() == str(tmp_path)
        assert session_module._get_tmux_contract_session_id() == "session-1"

        monkeypatch.delenv("TMPDIR")
        monkeypatch.delenv("TMP", raising=False)
        monkeypatch.delenv("TEMP", raising=False)

        with pytest.raises(ValueError):
            session_module._get_tmux_contract_tmpdir()

    @pytest.mark.unit
    def test_tmux_session_compatibility_allows_same_agent_native_rollover(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        row = SimpleNamespace(closed_at=None, native_session_id="old-native", active_agent="Claude")
        _install_sqlmodel_stub(monkeypatch, row=row)

        assert (
            session_module._is_tmux_contract_session_compatible(
                "session-1",
                "new-native",
                agent="claude",
            )
            is True
        )

    @pytest.mark.unit
    def test_tmux_session_compatibility_rejects_closed_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        row = SimpleNamespace(closed_at="2025-01-01T00:00:00+00:00", native_session_id="native", active_agent="claude")
        _install_sqlmodel_stub(monkeypatch, row=row)

        assert session_module._is_tmux_contract_session_compatible("session-1", "native", agent="claude") is False


class TestSessionRefreshAndResolution:
    @pytest.mark.unit
    def test_resolve_or_refresh_session_id_invalidates_missing_rows_and_detects_stale_native_ids(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        missing_session = _install_sqlmodel_stub(monkeypatch, row=None)

        assert session_module._resolve_or_refresh_session_id("session-1", "native-1", agent="claude") is None
        assert not missing_session.added

        row = SimpleNamespace(closed_at=None, native_session_id="old-native")
        refresh_session = _install_sqlmodel_stub(monkeypatch, row=row)

        assert session_module._resolve_or_refresh_session_id("session-2", "new-native", agent="claude") == "session-2"
        assert row.native_session_id == "old-native"
        assert not refresh_session.added
        assert refresh_session.committed is False

    @pytest.mark.unit
    def test_resolve_hook_session_id_mints_and_persists_headless_sessions_for_mint_events(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        persisted: list[tuple[str, str | None, str]] = []
        monkeypatch.setattr(session_module, "_get_cached_session_id", lambda agent, native: None)
        monkeypatch.setattr(session_module, "_resolve_or_refresh_session_id", lambda candidate, native, *, agent: None)
        monkeypatch.setattr(session_module, "_find_session_id_by_native", lambda native: None)
        monkeypatch.setattr(
            session_module,
            "_persist_session_map",
            lambda agent, native, session_id: persisted.append((agent, native, session_id)),
        )
        monkeypatch.setattr(session_module.uuid, "uuid4", lambda: "minted-session")

        resolved = session_module._resolve_hook_session_id(
            agent="claude",
            event_type="session.started",
            native_session_id="native-1",
            headless=True,
            mint_events=frozenset({"session.started"}),
        )

        assert resolved == ("minted-session", None, None)
        assert persisted == [("claude", "native-1", "minted-session")]

    @pytest.mark.unit
    def test_resolve_hook_session_id_falls_back_from_tmux_marker_to_native_lookup(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        persisted: list[tuple[str, str | None, str]] = []
        monkeypatch.setattr(session_module, "_get_tmux_contract_session_id", lambda: "marker-session")
        monkeypatch.setattr(
            session_module,
            "_is_tmux_contract_session_compatible",
            lambda session_id, native_session_id, *, agent: False,
        )
        monkeypatch.setattr(session_module, "_find_session_id_by_native", lambda native: "db-session")
        monkeypatch.setattr(
            session_module,
            "_persist_session_map",
            lambda agent, native, session_id: persisted.append((agent, native, session_id)),
        )

        resolved = session_module._resolve_hook_session_id(
            agent="claude",
            event_type="message.text",
            native_session_id="native-1",
            headless=False,
        )

        assert resolved == ("db-session", None, "marker-session")
        assert persisted == [("claude", "native-1", "db-session")]
