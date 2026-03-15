from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from sqlalchemy.sql.elements import TextClause

from teleclaude.core import db_models
from teleclaude.memory import store as store_module
from teleclaude.memory.types import ObservationInput

pytestmark = pytest.mark.unit

RowValue = tuple[object, ...]


@dataclass
class FakeExecResult:
    rowcount: int = 0
    rows: list[RowValue] = field(default_factory=list)

    def fetchall(self) -> list[RowValue]:
        return list(self.rows)

    def first(self) -> RowValue | None:
        return self.rows[0] if self.rows else None


class FakeAsyncSession:
    def __init__(self, exec_results: list[FakeExecResult] | None = None, refresh_id: int = 11) -> None:
        self.exec_results = list(exec_results or [])
        self.refresh_id = refresh_id
        self.added: list[db_models.MemoryObservation] = []
        self.committed = False
        self.statements: list[TextClause] = []

    def add(self, obj: db_models.MemoryObservation) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj: db_models.MemoryObservation) -> None:
        obj.id = self.refresh_id

    async def exec(self, statement: TextClause) -> FakeExecResult:
        self.statements.append(statement)
        return self.exec_results.pop(0)


@dataclass
class FakeAsyncSessionContext:
    session: FakeAsyncSession

    async def __aenter__(self) -> FakeAsyncSession:
        return self.session

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class FakeSyncSession:
    def __init__(self, refresh_id: int = 21) -> None:
        self.refresh_id = refresh_id
        self.added: list[db_models.MemoryObservation] = []
        self.committed = False

    def __enter__(self) -> FakeSyncSession:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def exec(self, statement: TextClause) -> FakeExecResult:
        assert str(statement).startswith("PRAGMA")
        return FakeExecResult()

    def add(self, obj: db_models.MemoryObservation) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True

    def refresh(self, obj: db_models.MemoryObservation) -> None:
        obj.id = self.refresh_id


def _observation_row(row_id: int, identity_key: str | None = None) -> RowValue:
    return (
        row_id,
        "session-1",
        "alpha",
        "discovery",
        "Stored title",
        None,
        '["fact"]',
        "Narrative",
        '["concept"]',
        None,
        None,
        None,
        0,
        "2025-01-01T00:00:00+00:00",
        1735689600,
        identity_key,
    )


class TestMemoryStore:
    async def test_save_observation_defaults_project_and_serializes_lists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = FakeAsyncSession(refresh_id=11)

        async def fake_get_or_create_manual_session(self: store_module.MemoryStore, project: str) -> str:
            assert project == store_module.DEFAULT_PROJECT
            return "manual-1"

        monkeypatch.setattr(
            store_module.MemoryStore,
            "_get_or_create_manual_session",
            fake_get_or_create_manual_session,
        )
        monkeypatch.setattr(store_module.db, "_session", lambda: FakeAsyncSessionContext(session))

        result = await store_module.MemoryStore().save_observation(
            ObservationInput(
                text="First sentence. More detail follows",
                concepts=["auth"],
                facts=["retry"],
                identity_key="user-1",
            )
        )

        assert result.id == 11
        assert result.title == "First sentence."
        assert result.project == store_module.DEFAULT_PROJECT
        assert len(session.added) == 1
        saved = session.added[0]
        assert saved.memory_session_id == "manual-1"
        assert saved.project == store_module.DEFAULT_PROJECT
        assert saved.title == "First sentence."
        assert saved.facts == '["retry"]'
        assert saved.concepts == '["auth"]'
        assert saved.identity_key == "user-1"
        assert session.committed is True

    def test_save_observation_sync_uses_sync_session_and_refreshes_saved_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = FakeSyncSession(refresh_id=21)

        def fake_get_or_create_manual_session_sync(self: store_module.MemoryStore, project: str, db_path: str) -> str:
            assert project == "alpha"
            assert db_path == "memory.sqlite"
            return "manual-sync"

        monkeypatch.setattr(
            store_module.MemoryStore, "_get_or_create_manual_session_sync", fake_get_or_create_manual_session_sync
        )
        monkeypatch.setattr(store_module, "create_engine", lambda url: url)
        monkeypatch.setattr(store_module, "SqlSession", lambda engine: session)

        result = store_module.MemoryStore().save_observation_sync(
            ObservationInput(text="Sync title", project="alpha"),
            db_path="memory.sqlite",
        )

        assert result.id == 21
        assert result.title == "Sync title"
        assert result.project == "alpha"
        assert len(session.added) == 1
        assert session.added[0].memory_session_id == "manual-sync"
        assert session.committed is True

    async def test_delete_observation_returns_true_when_rowcount_is_positive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = FakeAsyncSession(exec_results=[FakeExecResult(rowcount=1)])
        monkeypatch.setattr(store_module.db, "_session", lambda: FakeAsyncSessionContext(session))

        deleted = await store_module.MemoryStore().delete_observation(7)

        assert deleted is True
        assert session.statements[0].compile().params["id"] == 7
        assert session.committed is True

    async def test_get_by_ids_builds_project_filtered_query_and_converts_rows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = FakeAsyncSession(exec_results=[FakeExecResult(rows=[_observation_row(3, identity_key="user-1")])])
        monkeypatch.setattr(store_module.db, "_session", lambda: FakeAsyncSessionContext(session))

        results = await store_module.MemoryStore().get_by_ids([3, 4], project="alpha")

        assert [row.id for row in results] == [3]
        assert results[0].identity_key == "user-1"
        assert session.statements[0].compile().params["id_0"] == 3
        assert session.statements[0].compile().params["id_1"] == 4
        assert session.statements[0].compile().params["project"] == "alpha"
