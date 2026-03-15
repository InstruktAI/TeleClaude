from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from collections.abc import Iterator

import pytest

memories = importlib.import_module("teleclaude.cli.telec.handlers.memories")


@dataclass
class SearchCall:
    query: str
    limit: int
    obs_type: str | None
    project: str | None


class MemorySearchResult(TypedDict, total=False):
    id: int
    type: str
    project: str
    title: str
    narrative: str
    text: str


class MemorySaveResult(TypedDict):
    id: int
    title: str
    project: str


class FakeMemoryClient:
    search_call: SearchCall | None = None
    save_call: tuple[str, str | None, str | None, str | None] | None = None
    delete_call: int | None = None
    timeline_call: tuple[int, int, int, str | None] | None = None

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def memory_search(
        self, query: str, *, limit: int, obs_type: str | None, project: str | None
    ) -> list[MemorySearchResult]:
        type(self).search_call = SearchCall(query, limit, obs_type, project)
        return [{"id": 1, "type": "decision", "project": "telec", "title": "Title", "narrative": "Snippet"}]

    async def memory_save(
        self, text: str, *, title: str | None, obs_type: str | None, project: str | None
    ) -> MemorySaveResult:
        type(self).save_call = (text, title, obs_type, project)
        return {"id": 7, "title": title or "Generated", "project": project or "telec"}

    async def memory_delete(self, obs_id: int) -> MemorySaveResult:
        type(self).delete_call = obs_id
        return {"id": obs_id, "title": "Deleted", "project": "telec"}

    async def memory_timeline(
        self, anchor: int, *, before: int, after: int, project: str | None
    ) -> list[MemorySearchResult]:
        type(self).timeline_call = (anchor, before, after, project)
        return [
            {"id": anchor - 1, "type": "context", "project": "telec", "title": "Before", "narrative": "Earlier"},
            {"id": anchor, "type": "decision", "project": "telec", "title": "Anchor", "narrative": "Current"},
        ]


@pytest.fixture(autouse=True)
def _reset_fake_client() -> Iterator[None]:
    yield
    FakeMemoryClient.search_call = None
    FakeMemoryClient.save_call = None
    FakeMemoryClient.delete_call = None
    FakeMemoryClient.timeline_call = None


def test_handle_memories_routes_search(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[list[str]] = []

    monkeypatch.setattr(memories, "_handle_memories_search", lambda args: received.append(args))

    memories._handle_memories(["search", "needle"])

    assert received == [["needle"]]


def test_handle_memories_search_passes_parsed_filters(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(memories, "TelecAPIClient", FakeMemoryClient)

    memories._handle_memories_search(["release", "note", "--limit", "5", "--type", "decision", "--project", "telec"])

    assert FakeMemoryClient.search_call == SearchCall("release note", 5, "decision", "telec")
    assert "release note" in capsys.readouterr().out


def test_handle_memories_save_posts_observation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(memories, "TelecAPIClient", FakeMemoryClient)

    memories._handle_memories_save(["Learned this", "--title", "Finding", "--type", "discovery", "--project", "telec"])

    assert FakeMemoryClient.save_call == ("Learned this", "Finding", "discovery", "telec")
    assert "#7" in capsys.readouterr().out


def test_handle_memories_delete_rejects_non_numeric_ids(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        memories._handle_memories_delete(["abc"])

    assert exc_info.value.code == 1
    assert capsys.readouterr().out.strip()


def test_handle_memories_timeline_marks_anchor_entry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(memories, "TelecAPIClient", FakeMemoryClient)

    memories._handle_memories_timeline(["8", "--before", "2", "--after", "4", "--project", "telec"])

    assert FakeMemoryClient.timeline_call == (8, 2, 4, "telec")
    assert "◀" in capsys.readouterr().out
