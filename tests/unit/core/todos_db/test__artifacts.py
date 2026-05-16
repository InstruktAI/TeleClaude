"""RED tests for TodosDbArtifactsMixin — artifact persistence and versioning."""

from __future__ import annotations

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.constants import ARTIFACT_INPUT, ARTIFACT_PRD, ARTIFACT_REQUIREMENTS
from teleclaude.core.todos_db import TodosDb

pytestmark = pytest.mark.asyncio

_SLUG = "my-slug"


async def _ensure_roadmap_entry(db: TodosDb, slug: str = _SLUG) -> None:
    """Create the roadmap entry that artifact writes require."""
    await db.add_entry(slug=slug, position=0, description="test entry")


async def test_read_artifact_returns_empty_for_unknown_slug(
    todos_db: TodosDb,
    snapshot: SnapshotAssertion,
) -> None:
    assert await todos_db.read_artifact("nonexistent", ARTIFACT_REQUIREMENTS) == snapshot


async def test_read_artifact_sync_returns_empty_for_unknown_slug(
    todos_db: TodosDb,
    snapshot: SnapshotAssertion,
) -> None:
    assert todos_db.read_artifact_sync("nonexistent", ARTIFACT_REQUIREMENTS) == snapshot


async def test_artifact_digest_returns_empty_for_unknown_slug(
    todos_db: TodosDb,
    snapshot: SnapshotAssertion,
) -> None:
    assert await todos_db.artifact_digest("nonexistent", ARTIFACT_REQUIREMENTS) == snapshot


async def test_artifact_versions_returns_empty_list_for_unknown_slug(todos_db: TodosDb) -> None:
    assert await todos_db.artifact_versions("nonexistent", "requirements") == []


async def test_write_then_read_artifact_round_trips(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    content = "# Requirements\n\nContent here."
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, content)
    result = await todos_db.read_artifact(_SLUG, ARTIFACT_REQUIREMENTS)
    assert result == content


async def test_write_artifact_updates_existing(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    original = "v1"
    updated = "v2"
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, original)
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, updated)
    result = await todos_db.read_artifact(_SLUG, ARTIFACT_REQUIREMENTS)
    assert result == updated


async def test_write_artifact_stores_digest(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, ARTIFACT_INPUT, "some content")
    digest = await todos_db.artifact_digest(_SLUG, ARTIFACT_INPUT)
    assert isinstance(digest, str)
    assert len(digest) == 64  # SHA-256 hex


async def test_artifact_exists_returns_false_for_unknown_slug(todos_db: TodosDb) -> None:
    assert await todos_db.artifact_exists("nonexistent", "missing") is False


async def test_artifact_exists_returns_true_after_write(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, ARTIFACT_INPUT, "content")
    assert await todos_db.artifact_exists(_SLUG, ARTIFACT_INPUT) is True


async def test_list_artifacts_returns_names(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, ARTIFACT_INPUT, "a")
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, "b")
    names = await todos_db.list_artifacts(_SLUG)
    assert set(names) == {ARTIFACT_INPUT, ARTIFACT_REQUIREMENTS}


async def test_list_artifacts_returns_empty_for_unknown_slug(todos_db: TodosDb) -> None:
    assert await todos_db.list_artifacts("nonexistent") == []


async def test_write_artifact_creates_version_history(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    original = "v1"
    updated = "v2"
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, original)
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, updated)
    versions = await todos_db.artifact_versions(_SLUG, ARTIFACT_REQUIREMENTS)
    assert len(versions) == 2
    assert versions[0]["content"] == updated  # newest first
    assert versions[1]["content"] == original


async def test_artifacts_diff_returns_unified_diff_between_two_versions(
    todos_db: TodosDb,
    snapshot: SnapshotAssertion,
) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, "line one\nline two\n")
    digest_v1 = await todos_db.artifact_digest(_SLUG, ARTIFACT_REQUIREMENTS)
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, "line one\nline TWO\n")
    digest_v2 = await todos_db.artifact_digest(_SLUG, ARTIFACT_REQUIREMENTS)

    diff = await todos_db.artifacts_diff(_SLUG, ARTIFACT_REQUIREMENTS, digest_v1, digest_v2)

    assert diff == snapshot


async def test_artifacts_diff_returns_empty_when_digests_match(
    todos_db: TodosDb,
    snapshot: SnapshotAssertion,
) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, "same content\n")
    digest = await todos_db.artifact_digest(_SLUG, ARTIFACT_REQUIREMENTS)

    diff = await todos_db.artifacts_diff(_SLUG, ARTIFACT_REQUIREMENTS, digest, digest)

    assert diff == snapshot


async def test_artifacts_diff_raises_when_both_digests_match_unknown_value(
    todos_db: TodosDb,
) -> None:
    """Identical-but-unknown digests must raise; the empty-diff short-circuit must not hide invalid input."""
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, "content\n")

    with pytest.raises(ValueError):
        await todos_db.artifacts_diff(_SLUG, ARTIFACT_REQUIREMENTS, "deadbeef" * 8, "deadbeef" * 8)


async def test_artifacts_diff_raises_for_unknown_old_digest(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, "content\n")
    new_digest = await todos_db.artifact_digest(_SLUG, ARTIFACT_REQUIREMENTS)

    with pytest.raises(ValueError):
        await todos_db.artifacts_diff(_SLUG, ARTIFACT_REQUIREMENTS, "deadbeef" * 8, new_digest)


async def test_artifacts_diff_raises_for_unknown_new_digest(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, "content\n")
    old_digest = await todos_db.artifact_digest(_SLUG, ARTIFACT_REQUIREMENTS)

    with pytest.raises(ValueError):
        await todos_db.artifacts_diff(_SLUG, ARTIFACT_REQUIREMENTS, old_digest, "deadbeef" * 8)


async def test_delete_artifacts_removes_all_for_slug(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, ARTIFACT_INPUT, "a")
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, "b")
    await todos_db.delete_artifacts(_SLUG)
    assert await todos_db.list_artifacts(_SLUG) == []


async def test_delete_artifacts_removes_version_history(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, "v1")
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, "v2")
    await todos_db.delete_artifacts(_SLUG)
    versions = await todos_db.artifact_versions(_SLUG, ARTIFACT_REQUIREMENTS)
    assert versions == []


async def test_delete_artifacts_is_noop_when_roadmap_entry_missing(todos_db: TodosDb) -> None:
    """Deleting artifacts for a slug with no roadmap entry should not raise."""
    await todos_db.delete_artifacts("nonexistent-slug")  # must not raise ValueError


async def test_delete_artifact_removes_only_named_artifact_and_versions(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, ARTIFACT_INPUT, "input")
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, "requirements-v1")
    await todos_db.write_artifact(_SLUG, ARTIFACT_REQUIREMENTS, "requirements-v2")
    await todos_db.write_artifact(_SLUG, ARTIFACT_PRD, "prd")

    result = await todos_db.delete_artifact(_SLUG, ARTIFACT_REQUIREMENTS)

    assert result["removed"] is True
    assert result["versions_deleted"] == 2
    assert set(await todos_db.list_artifacts(_SLUG)) == {ARTIFACT_INPUT, ARTIFACT_PRD}
    assert await todos_db.artifact_versions(_SLUG, ARTIFACT_REQUIREMENTS) == []


async def test_delete_artifact_is_noop_for_missing_artifact(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)

    result = await todos_db.delete_artifact(_SLUG, ARTIFACT_REQUIREMENTS)

    assert result["removed"] is False
    assert result["versions_deleted"] == 0


async def test_delete_artifact_raises_for_unknown_slug(todos_db: TodosDb) -> None:
    with pytest.raises(ValueError):
        await todos_db.delete_artifact("nonexistent-slug", ARTIFACT_REQUIREMENTS)
