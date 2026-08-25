"""Closed ownership of the artifacts that make a review verdict current."""

from __future__ import annotations

from dataclasses import dataclass

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE_REVIEW_FINDINGS,
    ARTIFACT_PLAN_REVIEW_FINDINGS,
    ARTIFACT_PRD_REVIEW_FINDINGS,
    ARTIFACT_REVIEW_FINDINGS,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_PRD,
)


@dataclass(frozen=True)
class ReviewEvidenceArtifacts:
    """The reviewed target and durable report for one live review phase."""

    target_artifact_key: str | None
    report_artifact_name: str


REVIEW_EVIDENCE_ARTIFACTS: dict[str, ReviewEvidenceArtifacts] = {
    "prd_review": ReviewEvidenceArtifacts(STATE_KEY_PRD, ARTIFACT_PRD_REVIEW_FINDINGS),
    "architecture_review": ReviewEvidenceArtifacts(STATE_KEY_ARCHITECTURE, ARTIFACT_ARCHITECTURE_REVIEW_FINDINGS),
    "plan_review": ReviewEvidenceArtifacts(STATE_KEY_IMPLEMENTATION_PLAN, ARTIFACT_PLAN_REVIEW_FINDINGS),
    "build_review": ReviewEvidenceArtifacts(None, ARTIFACT_REVIEW_FINDINGS),
}

PREPARE_REVIEW_PHASES = tuple(
    phase for phase, artifacts in REVIEW_EVIDENCE_ARTIFACTS.items() if artifacts.target_artifact_key
)
BUILD_REVIEW_PHASE = "build_review"
