"""Tests for drift provenance fields on todo state models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from teleclaude.types.todos import (
    ArtifactEntry,
    DependencyEntry,
    DriftReviewedStamp,
    ReviewVerdictState,
    TodoState,
)

_ARCHITECTURE_ARTIFACT = "architecture"
_COSMETIC_VERDICT = "cosmetic"
_DEPENDENCY_SLUG = "dependency-slug"
_MISSING_STATUS_ENTRY = {"dep_slug": _DEPENDENCY_SLUG}
_UNKNOWN_STATUS_ENTRY = {"dep_slug": _DEPENDENCY_SLUG, "roadmap_status": "unknown"}


pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


def test_artifact_entry_defaults_to_empty_drift_provenance() -> None:
    entry = ArtifactEntry()

    assert entry.owned_snippet_digests == {}
    assert entry.referenced_snippet_digests == {}
    assert entry.dependency_set_at_write == []
    assert entry.async_provenance_complete is False


def test_drift_reviewed_stamp_defaults_to_empty_evidence_anchor() -> None:
    stamp = DriftReviewedStamp(verdict=_COSMETIC_VERDICT)

    assert stamp.head_sha_at_review == ""
    assert stamp.upstream_digests_at_review == {}
    assert stamp.snippet_digests_at_review == {}
    assert stamp.dep_set_at_review == []


def test_review_verdict_state_defaults_to_not_cleared_by_substantive_drift() -> None:
    verdict = ReviewVerdictState()

    assert verdict.cleared_by_substantive_drift is False


def test_dependency_entry_rejects_missing_status() -> None:
    with pytest.raises(ValidationError):
        DependencyEntry.model_validate(_MISSING_STATUS_ENTRY)


def test_dependency_entry_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        DependencyEntry.model_validate(_UNKNOWN_STATUS_ENTRY)


def test_legacy_todo_state_loads_with_drift_field_defaults() -> None:
    legacy_payload = TodoState.defaults().model_dump()
    legacy_payload["artifacts"][_ARCHITECTURE_ARTIFACT].pop("owned_snippet_digests", None)
    legacy_payload["artifacts"][_ARCHITECTURE_ARTIFACT].pop("referenced_snippet_digests", None)
    legacy_payload["artifacts"][_ARCHITECTURE_ARTIFACT].pop("dependency_set_at_write", None)
    legacy_payload["artifacts"][_ARCHITECTURE_ARTIFACT].pop("async_provenance_complete", None)

    loaded = TodoState.model_validate(legacy_payload)

    entry = loaded.artifacts.architecture
    assert entry.owned_snippet_digests == {}
    assert entry.referenced_snippet_digests == {}
    assert entry.dependency_set_at_write == []
    assert entry.async_provenance_complete is False
