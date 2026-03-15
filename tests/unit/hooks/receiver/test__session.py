"""Characterization tests for teleclaude.hooks.receiver._session."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import teleclaude.hooks.receiver._session as session_module


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


def _install_sqlmodel_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    row: object | None = None,
    first: object | None = None,
) -> _SqlSessionStub:
    session_stub = _SqlSessionStub(row=row, first=first)
    module = types.ModuleType("sqlmodel")
    module.Session = lambda _engine: session_stub
    module.select = lambda _model: _SelectStub()
    monkeypatch.setitem(sys.modules, "sqlmodel", module)
    monkeypatch.setattr(session_module, "_create_sync_engine", lambda: object())
    return session_stub


class TestMemoryAndSessionMap:
    @pytest.mark.unit
    def test_get_memory_context_returns_generated_context_and_empty_string_on_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        memory_context = types.ModuleType("teleclaude.memory.context")
        memory_context.generate_context_sync = lambda project_name, db_path, identity_key=None: (
            f"{project_name}|{db_path}|{identity_key}"
        )
        monkeypatch.setitem(sys.modules, "teleclaude.memory.context", memory_context)
        monkeypatch.setattr(
            session_module, "config", SimpleNamespace(database=SimpleNamespace(path=Path("/tmp/db.sqlite")))
        )

        assert session_module._get_memory_context("teleclaude", "user-1") == "teleclaude|/tmp/db.sqlite|user-1"

        memory_context.generate_context_sync = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))

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


class TestTmuxContractResolution:
    @pytest.mark.unit
    def test_tmux_contract_reads_the_marker_file_and_uses_tmpdir_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        marker = tmp_path / "teleclaude_session_id"
        marker.write_text("session-1\n", encoding="utf-8")
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
    def test_resolve_or_refresh_session_id_invalidates_missing_rows_and_updates_stale_native_ids(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        missing_session = _install_sqlmodel_stub(monkeypatch, row=None)

        assert session_module._resolve_or_refresh_session_id("session-1", "native-1", agent="claude") is None
        assert missing_session.added == []

        row = SimpleNamespace(closed_at=None, native_session_id="old-native")
        refresh_session = _install_sqlmodel_stub(monkeypatch, row=row)

        assert session_module._resolve_or_refresh_session_id("session-2", "new-native", agent="claude") == "session-2"
        assert row.native_session_id == "new-native"
        assert refresh_session.added == [row]
        assert refresh_session.committed is True

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
