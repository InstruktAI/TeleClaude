"""Functional bindings for historical conversation search default exclusions."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.mirrors import store

pytestmark = [pytest.mark.functional]

_SPEC = "project/spec/feature/session_mirrors/historical-conversation-search"


def _record(source: str, *, is_spawn: bool, title: str) -> store.MirrorRecord:
    return store.MirrorRecord(
        session_id=source,
        computer="box",
        agent="claude",
        project="proj",
        title=title,
        timestamp_start="2026-06-01T00:00:00Z",
        timestamp_end="2026-06-01T00:00:00Z",
        conversation_text="ordering by recency keyword",
        message_count=1,
        metadata={},
        created_at="2026-06-01T00:00:00Z",
        updated_at="2026-06-01T00:00:00Z",
        source_identity=source,
        is_agent_spawn=is_spawn,
        command="next-build" if is_spawn else None,
        slug="some-slug" if is_spawn else None,
        derivation_version=1,
    )


@pytest.mark.spec(_SPEC, "UC-HCS-4")
def test_agent_spawn_rows_excluded_from_search_but_fetchable_by_id(tmp_path: Path) -> None:
    db = str(tmp_path / "search.db")
    store.upsert_mirror(_record("human-row", is_spawn=False, title="Human asks about ordering"), db=db)
    store.upsert_mirror(_record("spawn-row", is_spawn=True, title="Build: some-slug"), db=db)

    hits = store.search_mirrors("ordering", agents=[], db=db)
    session_ids = {hit.session_id for hit in hits}
    assert session_ids == {"human-row"}

    # Provenance preserved: the excluded spawn row is still fetchable by exact id.
    spawn = store.get_mirror("spawn-row", db=db)
    assert spawn is not None
    assert spawn.is_agent_spawn is True
