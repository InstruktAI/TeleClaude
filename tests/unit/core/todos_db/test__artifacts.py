"""RED tests for TodosDbArtifactsMixin — artifact persistence and versioning."""

from __future__ import annotations

import pytest

from teleclaude.core.todos_db import TodosDb

pytestmark = pytest.mark.asyncio

_SLUG = "my-slug"


async def _ensure_roadmap_entry(db: TodosDb, slug: str = _SLUG) -> None:
    """Create the roadmap entry that artifact writes require."""
    await db.add_entry(slug=slug, position=0, description="test entry")


async def test_read_artifact_returns_empty_for_unknown_slug(todos_db: TodosDb) -> None:
    assert await todos_db.read_artifact("nonexistent", "requirements") == ""


async def test_write_then_read_artifact_round_trips(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, "requirements", "# Requirements\n\nContent here.")
    result = await todos_db.read_artifact(_SLUG, "requirements")
    assert result == "# Requirements\n\nContent here."


async def test_write_artifact_updates_existing(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, "requirements", "v1")
    await todos_db.write_artifact(_SLUG, "requirements", "v2")
    result = await todos_db.read_artifact(_SLUG, "requirements")
    assert result == "v2"


async def test_write_artifact_stores_digest(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, "input", "some content")
    digest = await todos_db.artifact_digest(_SLUG, "input")
    assert isinstance(digest, str)
    assert len(digest) == 64  # SHA-256 hex


async def test_artifact_exists_returns_false_for_unknown_slug(todos_db: TodosDb) -> None:
    assert await todos_db.artifact_exists("nonexistent", "missing") is False


async def test_artifact_exists_returns_true_after_write(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, "input", "content")
    assert await todos_db.artifact_exists(_SLUG, "input") is True


async def test_list_artifacts_returns_names(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, "input", "a")
    await todos_db.write_artifact(_SLUG, "requirements", "b")
    names = await todos_db.list_artifacts(_SLUG)
    assert set(names) == {"input", "requirements"}


async def test_list_artifacts_returns_empty_for_unknown_slug(todos_db: TodosDb) -> None:
    assert await todos_db.list_artifacts("nonexistent") == []


async def test_write_artifact_creates_version_history(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, "requirements", "v1")
    await todos_db.write_artifact(_SLUG, "requirements", "v2")
    versions = await todos_db.artifact_versions(_SLUG, "requirements")
    assert len(versions) == 2
    assert versions[0]["content"] == "v2"  # newest first
    assert versions[1]["content"] == "v1"


async def test_artifacts_diff_returns_unified_diff_between_two_versions(
    todos_db: TodosDb,
) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, "requirements", "line one\nline two\n")
    digest_v1 = await todos_db.artifact_digest(_SLUG, "requirements")
    await todos_db.write_artifact(_SLUG, "requirements", "line one\nline TWO\n")
    digest_v2 = await todos_db.artifact_digest(_SLUG, "requirements")

    diff = await todos_db.artifacts_diff(_SLUG, "requirements", digest_v1, digest_v2)

    assert "-line two" in diff
    assert "+line TWO" in diff


async def test_artifacts_diff_returns_empty_when_digests_match(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, "requirements", "same content\n")
    digest = await todos_db.artifact_digest(_SLUG, "requirements")

    diff = await todos_db.artifacts_diff(_SLUG, "requirements", digest, digest)

    assert diff == ""


async def test_artifacts_diff_raises_when_both_digests_match_unknown_value(
    todos_db: TodosDb,
) -> None:
    """Identical-but-unknown digests must raise; the empty-diff short-circuit must not hide invalid input."""
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, "requirements", "content\n")

    with pytest.raises(ValueError, match=r"no version with digest"):
        await todos_db.artifacts_diff(_SLUG, "requirements", "deadbeef" * 8, "deadbeef" * 8)


async def test_artifacts_diff_raises_for_unknown_old_digest(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, "requirements", "content\n")
    new_digest = await todos_db.artifact_digest(_SLUG, "requirements")

    with pytest.raises(ValueError, match=r"no version with digest"):
        await todos_db.artifacts_diff(_SLUG, "requirements", "deadbeef" * 8, new_digest)


async def test_artifacts_diff_raises_for_unknown_new_digest(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, "requirements", "content\n")
    old_digest = await todos_db.artifact_digest(_SLUG, "requirements")

    with pytest.raises(ValueError, match=r"no version with digest"):
        await todos_db.artifacts_diff(_SLUG, "requirements", old_digest, "deadbeef" * 8)


async def test_delete_artifacts_removes_all_for_slug(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, "input", "a")
    await todos_db.write_artifact(_SLUG, "requirements", "b")
    await todos_db.delete_artifacts(_SLUG)
    assert await todos_db.list_artifacts(_SLUG) == []


async def test_delete_artifacts_removes_version_history(todos_db: TodosDb) -> None:
    await _ensure_roadmap_entry(todos_db)
    await todos_db.write_artifact(_SLUG, "requirements", "v1")
    await todos_db.write_artifact(_SLUG, "requirements", "v2")
    await todos_db.delete_artifacts(_SLUG)
    versions = await todos_db.artifact_versions(_SLUG, "requirements")
    assert versions == []


async def test_delete_artifacts_is_noop_when_roadmap_entry_missing(todos_db: TodosDb) -> None:
    """Deleting artifacts for a slug with no roadmap entry should not raise."""
    await todos_db.delete_artifacts("nonexistent-slug")  # must not raise ValueError
