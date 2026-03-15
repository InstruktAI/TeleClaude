from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy.sql.elements import TextClause

from teleclaude.memory import search as search_module
from teleclaude.memory.types import ObservationType

pytestmark = pytest.mark.unit

SearchRow = tuple[int, str | None, str | None, str, str, str | None, str | None, str, int]
RowValue = tuple[object, ...]


@dataclass
class FakeResult:
    rows: list[RowValue]

    def fetchall(self) -> list[RowValue]:
        return list(self.rows)

    def first(self) -> RowValue | None:
        return self.rows[0] if self.rows else None


class FakeAsyncSession:
    def __init__(self, outcomes: list[Exception | list[RowValue]]) -> None:
        self._outcomes = list(outcomes)
        self.statements: list[TextClause] = []

    async def exec(self, statement: TextClause) -> FakeResult:
        self.statements.append(statement)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResult(outcome)


@dataclass
class FakeAsyncSessionContext:
    session: FakeAsyncSession

    async def __aenter__(self) -> FakeAsyncSession:
        return self.session

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class FakeSyncSession:
    def __init__(self, outcomes: list[Exception | list[RowValue]]) -> None:
        self._outcomes = list(outcomes)
        self.statements: list[TextClause] = []

    def __enter__(self) -> FakeSyncSession:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def exec(self, statement: TextClause) -> FakeResult:
        if str(statement).startswith("PRAGMA"):
            return FakeResult([])
        self.statements.append(statement)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResult(outcome)


def _search_row(
    row_id: int,
    title: str,
    *,
    narrative: str | None = None,
    facts: str | None = None,
    created_at_epoch: int = 100,
) -> SearchRow:
    return (
        row_id,
        title,
        None,
        "discovery",
        "alpha",
        narrative,
        facts,
        "2025-01-01T00:00:00+00:00",
        created_at_epoch,
    )


class TestMemorySearch:
    async def test_search_falls_back_to_like_when_fts_query_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = FakeAsyncSession(
            [
                RuntimeError("fts unavailable"),
                [
                    _search_row(
                        1, "Cache invalidation", narrative="Remember to retry", facts='["retry"]', created_at_epoch=1
                    )
                ],
            ]
        )
        monkeypatch.setattr(search_module.db, "_session", lambda: FakeAsyncSessionContext(session))

        results = await search_module.MemorySearch().search(
            "cache",
            project="alpha",
            limit=3,
            obs_type=ObservationType.DISCOVERY,
            identity_key="user-1",
        )

        assert [result.id for result in results] == [1]
        assert results[0].facts == ["retry"]
        assert "MATCH" in str(session.statements[0])
        assert "LIKE" in str(session.statements[1])
        assert session.statements[0].compile().params["query"] == "cache"
        assert session.statements[1].compile().params["pattern"] == "%cache%"
        assert session.statements[1].compile().params["identity_key"] == "user-1"

    async def test_timeline_returns_before_anchor_after_in_time_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = FakeAsyncSession(
            [
                [(1000,)],
                [_search_row(2, "Near", created_at_epoch=900), _search_row(1, "Far", created_at_epoch=800)],
                [_search_row(10, "Anchor", created_at_epoch=1000)],
                [_search_row(11, "After", created_at_epoch=1100)],
            ]
        )
        monkeypatch.setattr(search_module.db, "_session", lambda: FakeAsyncSessionContext(session))

        results = await search_module.MemorySearch().timeline(
            anchor_id=10, depth_before=2, depth_after=1, project="alpha"
        )

        assert [result.id for result in results] == [1, 2, 10, 11]
        assert session.statements[0].compile().params["id"] == 10
        assert session.statements[1].compile().params["project"] == "alpha"
        assert session.statements[3].compile().params["limit"] == 1

    async def test_batch_fetch_returns_empty_without_ids(self) -> None:
        assert await search_module.MemorySearch().batch_fetch([]) == []

    def test_search_sync_uses_like_fallback_after_fts_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = FakeSyncSession(
            [
                RuntimeError("fts unavailable"),
                [_search_row(5, "Sync fallback", narrative="Use LIKE", facts='["like"]', created_at_epoch=5)],
            ]
        )
        monkeypatch.setattr(search_module, "create_engine", lambda url: url)
        monkeypatch.setattr(search_module, "SqlSession", lambda engine: session)

        results = search_module.MemorySearch().search_sync("sync", project="alpha", limit=2, db_path="memory.sqlite")

        assert [result.id for result in results] == [5]
        assert results[0].facts == ["like"]
        assert "MATCH" in str(session.statements[0])
        assert "LIKE" in str(session.statements[1])
        assert session.statements[1].compile().params["project"] == "alpha"
