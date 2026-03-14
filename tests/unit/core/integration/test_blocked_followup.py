"""Characterization tests for teleclaude.core.integration.blocked_followup."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.core.integration.blocked_followup import (
    BlockedFollowUpError,
    BlockedFollowUpLink,
    BlockedFollowUpStore,
)
from teleclaude.core.integration.events import IntegrationBlockedPayload
from teleclaude.core.integration.readiness_projection import CandidateKey

_BLOCKED_AT = "2024-01-01T12:00:00+00:00"


def _make_payload(
    slug: str = "my-slug",
    branch: str = "my-branch",
    sha: str = "abc1234",
    *,
    follow_up_slug: str = "",
) -> IntegrationBlockedPayload:
    payload: IntegrationBlockedPayload = {
        "slug": slug,
        "branch": branch,
        "sha": sha,
        "conflict_evidence": ["file.py has conflicts"],
        "diagnostics": ["merge failed"],
        "next_action": "Resolve conflicts",
        "blocked_at": _BLOCKED_AT,
    }
    if follow_up_slug:
        payload["follow_up_slug"] = follow_up_slug
    return payload


def _make_store(tmp_path: Path) -> BlockedFollowUpStore:
    return BlockedFollowUpStore(
        state_path=tmp_path / "blocked.json",
        todos_root=tmp_path / "todos",
    )


# ---------------------------------------------------------------------------
# ensure_follow_up (create)
# ---------------------------------------------------------------------------


def test_ensure_follow_up_creates_link(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    payload = _make_payload()
    link = store.ensure_follow_up(payload)
    assert isinstance(link, BlockedFollowUpLink)
    assert link.key.slug == "my-slug"
    assert link.status == "open"
    assert link.follow_up_slug != ""


def test_ensure_follow_up_uses_preferred_slug_when_provided(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    payload = _make_payload(follow_up_slug="custom-slug")
    link = store.ensure_follow_up(payload)
    assert link.follow_up_slug == "custom-slug"


def test_ensure_follow_up_creates_todo_files(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    payload = _make_payload()
    link = store.ensure_follow_up(payload)
    todo_dir = tmp_path / "todos" / link.follow_up_slug
    assert (todo_dir / "requirements.md").exists()
    assert (todo_dir / "implementation-plan.md").exists()
    assert (todo_dir / "state.yaml").exists()


def test_ensure_follow_up_is_idempotent_for_same_candidate(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    payload = _make_payload()
    link1 = store.ensure_follow_up(payload)
    link2 = store.ensure_follow_up(payload)
    assert link1.follow_up_slug == link2.follow_up_slug
    assert len(store.links()) == 1


def test_ensure_follow_up_updates_evidence_on_repeat_call(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    payload1 = _make_payload()
    store.ensure_follow_up(payload1)
    payload2 = {**payload1, "conflict_evidence": ["new-file.py"], "blocked_at": "2024-06-01T00:00:00+00:00"}
    link2 = store.ensure_follow_up(payload2)
    assert "new-file.py" in link2.last_conflict_evidence


# ---------------------------------------------------------------------------
# mark_resolved
# ---------------------------------------------------------------------------


def test_mark_resolved_changes_status_to_resolved(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    payload = _make_payload()
    link = store.ensure_follow_up(payload)
    resolved = store.mark_resolved(follow_up_slug=link.follow_up_slug)
    assert resolved.status == "resolved"
    assert resolved.resolved_at is not None


def test_mark_resolved_raises_for_unknown_slug(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    with pytest.raises(BlockedFollowUpError):
        store.mark_resolved(follow_up_slug="nonexistent-slug")


# ---------------------------------------------------------------------------
# candidate_for_follow_up / get_by_candidate
# ---------------------------------------------------------------------------


def test_candidate_for_follow_up_returns_key(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    link = store.ensure_follow_up(_make_payload())
    key = store.candidate_for_follow_up(follow_up_slug=link.follow_up_slug)
    assert key == link.key


def test_candidate_for_follow_up_returns_none_for_unknown(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.candidate_for_follow_up(follow_up_slug="unknown") is None


def test_get_by_candidate_returns_link(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    link = store.ensure_follow_up(_make_payload())
    found = store.get_by_candidate(key=link.key)
    assert found is not None
    assert found.follow_up_slug == link.follow_up_slug


def test_get_by_candidate_returns_none_for_unknown(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    key = CandidateKey(slug="missing", branch="b", sha="s")
    assert store.get_by_candidate(key=key) is None


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------


def test_store_persists_links_across_reload(tmp_path: Path) -> None:
    state_path = tmp_path / "blocked.json"
    todos_root = tmp_path / "todos"
    s1 = BlockedFollowUpStore(state_path=state_path, todos_root=todos_root)
    link = s1.ensure_follow_up(_make_payload())

    s2 = BlockedFollowUpStore(state_path=state_path, todos_root=todos_root)
    found = s2.get_by_candidate(key=link.key)
    assert found is not None
    assert found.follow_up_slug == link.follow_up_slug


def test_store_raises_on_corrupt_json(tmp_path: Path) -> None:
    state_path = tmp_path / "blocked.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("not json", encoding="utf-8")
    with pytest.raises(BlockedFollowUpError):
        BlockedFollowUpStore(state_path=state_path, todos_root=tmp_path / "todos")
