"""Tests for drift provenance state synchronization."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine.provenance import (
    clear_artifact_provenance,
    extract_snippet_refs,
    sync_artifact_provenance,
    sync_artifact_provenance_sync_subset,
)
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.types.todos import DependencyEntry, DriftReviewedStamp, TodoState

_SLUG = "my-slug"
_ARCHITECTURE = "architecture"
_ARCHITECTURE_DIGEST = "architecture-digest"
_HEAD_SHA = "origin-main-sha"
_SRC_APP = "src/app.py"
_SNIPPET_ID = "project/spec/example"
_SNIPPET_DIGEST = "snippet-digest"
_DEPENDENCY = DependencyEntry(dep_slug="dep", roadmap_status="active")
_EMPTY = ""


pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


async def test_sync_artifact_provenance_populates_full_drift_evidence() -> None:
    todos_db = AsyncMock()
    todos_db.artifact_digest = AsyncMock(return_value=_ARCHITECTURE_DIGEST)
    writer = StateWriter(TodoState.defaults().model_dump())
    writer.state.artifacts.prd.digest = "prd-digest"

    with (
        patch("teleclaude.core.next_machine.provenance.get_origin_main_sha", return_value=_HEAD_SHA),
        patch("teleclaude.core.next_machine.provenance.extract_referenced_paths", return_value=[_SRC_APP]),
        patch(
            "teleclaude.core.next_machine.provenance.read_owned_snippet_digests",
            new=AsyncMock(return_value={_SNIPPET_ID: _SNIPPET_DIGEST}),
        ),
        patch(
            "teleclaude.core.next_machine.provenance.read_referenced_snippet_digests",
            new=AsyncMock(return_value={_SNIPPET_ID: _SNIPPET_DIGEST}),
        ),
        patch("teleclaude.core.next_machine.provenance.read_dependency_set", new=AsyncMock(return_value=[_DEPENDENCY])),
    ):
        await sync_artifact_provenance(
            todos_db,
            writer,
            _SLUG,
            _ARCHITECTURE,
            repo_root="/repo",
            artifact_body=_SRC_APP,
            snippet_digest_fn=lambda _snippet_id: _SNIPPET_DIGEST,
        )

    entry = writer.state.artifacts.architecture
    assert entry.digest == _ARCHITECTURE_DIGEST
    assert entry.codebase_sha_at_write == _HEAD_SHA
    assert entry.referenced_paths == [_SRC_APP]
    assert entry.upstream_digests == {"prd": "prd-digest"}
    assert entry.owned_snippet_digests == {_SNIPPET_ID: _SNIPPET_DIGEST}
    assert entry.referenced_snippet_digests == {_SNIPPET_ID: _SNIPPET_DIGEST}
    assert entry.dependency_set_at_write == [_DEPENDENCY]
    assert entry.produced_at
    assert entry.async_provenance_complete is True


def test_sync_subset_refresh_clears_async_only_provenance_and_drift_state() -> None:
    writer = StateWriter(TodoState.defaults().model_dump())
    entry = writer.state.artifacts.architecture
    entry.owned_snippet_digests = {_SNIPPET_ID: _SNIPPET_DIGEST}
    entry.referenced_snippet_digests = {_SNIPPET_ID: _SNIPPET_DIGEST}
    entry.dependency_set_at_write = [_DEPENDENCY]
    entry.async_provenance_complete = True
    writer.state.approvals.drift_reviewed[_ARCHITECTURE] = DriftReviewedStamp(verdict="cosmetic")
    writer.state.architecture_review.cleared_by_substantive_drift = True

    sync_artifact_provenance_sync_subset(
        writer,
        _SLUG,
        _ARCHITECTURE,
        repo_root="/repo",
        sha_at_write=_HEAD_SHA,
        referenced_paths=[_SRC_APP],
        digest=_ARCHITECTURE_DIGEST,
    )

    assert entry.digest == _ARCHITECTURE_DIGEST
    assert entry.codebase_sha_at_write == _HEAD_SHA
    assert entry.referenced_paths == [_SRC_APP]
    assert entry.owned_snippet_digests == {}
    assert entry.referenced_snippet_digests == {}
    assert entry.dependency_set_at_write == []
    assert entry.async_provenance_complete is False
    assert _ARCHITECTURE not in writer.state.approvals.drift_reviewed
    assert writer.state.architecture_review.cleared_by_substantive_drift is False


def test_clear_artifact_provenance_removes_all_drift_evidence() -> None:
    writer = StateWriter(TodoState.defaults().model_dump())
    entry = writer.state.artifacts.architecture
    entry.digest = _ARCHITECTURE_DIGEST
    entry.produced_at = "2026-01-01T00:00:00+00:00"
    entry.codebase_sha_at_write = _HEAD_SHA
    entry.referenced_paths = [_SRC_APP]
    entry.upstream_digests = {"prd": "prd-digest"}
    entry.owned_snippet_digests = {_SNIPPET_ID: _SNIPPET_DIGEST}
    entry.referenced_snippet_digests = {_SNIPPET_ID: _SNIPPET_DIGEST}
    entry.dependency_set_at_write = [_DEPENDENCY]
    entry.async_provenance_complete = True
    writer.state.approvals.drift_reviewed[_ARCHITECTURE] = DriftReviewedStamp(verdict="cosmetic")
    writer.state.architecture_review.cleared_by_substantive_drift = True

    clear_artifact_provenance(writer, _SLUG, _ARCHITECTURE)

    assert entry.digest == _EMPTY
    assert entry.produced_at == _EMPTY
    assert entry.codebase_sha_at_write == _EMPTY
    assert entry.referenced_paths == []
    assert entry.upstream_digests == {}
    assert entry.owned_snippet_digests == {}
    assert entry.referenced_snippet_digests == {}
    assert entry.dependency_set_at_write == []
    assert entry.async_provenance_complete is False
    assert _ARCHITECTURE not in writer.state.approvals.drift_reviewed
    assert writer.state.architecture_review.cleared_by_substantive_drift is False


def test_extract_snippet_refs_accepts_validator_supported_forms() -> None:
    home_ref = f"@{Path.home()}/.teleclaude/docs/general/policy/example.md"
    body = f"{home_ref}\n@docs/project/spec/example.md\n@snippet/ignored.md"

    assert extract_snippet_refs(body, "/repo") == [
        "general/policy/example",
        "project/spec/example",
    ]
