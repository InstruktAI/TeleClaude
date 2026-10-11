"""Immutable identities and outcomes for one serialized release attempt."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from teleclaude.git import GitCommandError, Repo

_REMOTE_MAIN_COMMIT = "refs/remotes/origin/main^{commit}"
_COMMIT_SUFFIX = "^{commit}"
_BASELINE_TAG_REQUIRED = "A normal release attempt requires a completed publication baseline."
_BASELINE_PAIR_REQUIRED = "Baseline tag and commit must either both be present or both be absent."
_BASELINE_NOT_ANCESTOR = "The completed publication baseline is not an ancestor of captured source."
_SOURCE_COMMIT_UNAVAILABLE = "Canonical origin/main did not resolve to a commit."
_BASELINE_COMMIT_UNAVAILABLE = "The completed publication tag did not resolve to a commit."
_NO_COMPLETED_RELEASE = "No completed semantic GitHub release is available as a baseline."
_ATTEMPT_SOURCE_MISMATCH = "The checkout does not match the captured source revision."
_ATTEMPT_BASELINE_MISMATCH = "The completed publication tag does not match the captured baseline commit."
_UTF8_ENCODING = "utf-8"
_IS_ANCESTOR_ARGUMENT = "--is-ancestor"
_HEAD_REFERENCE = "HEAD"
_VERIFY_ARGUMENT = "--verify"
_SEMANTIC_TAG_PATTERN = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


class ProviderName(StrEnum):
    """Provider identities admitted by the release-inspection protocol."""

    CODEX = "codex"
    CLAUDE = "claude"


class ProviderOutcome(StrEnum):
    """Terminal result of one provider attempt."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProviderFailure(StrEnum):
    """Structured failure categories retained independently of report prose."""

    AVAILABILITY = "availability"
    EXECUTION = "execution"
    INVALID_REPORT = "invalid_report"
    INCOMPLETE = "incomplete"
    AUTH_SETTLEMENT = "auth_settlement"


class PublicationState(StrEnum):
    """Durable publication lifecycle state carried by a receipt."""

    PROVED = "proved"
    PUBLISHING = "publishing"
    PUBLISHED = "published"


class ImmutableRecord(BaseModel):
    """Base contract for strict, immutable release records."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class AttemptIdentity(ImmutableRecord):
    """Source, baseline, and workflow identity captured after serialization."""

    repository: str
    workflow_run_id: str
    workflow_run_attempt: int
    source_sha: str
    baseline_tag: str | None
    baseline_sha: str | None
    bootstrap: bool

    @model_validator(mode="after")
    def validate_baseline_pair(self) -> AttemptIdentity:
        """Require a baseline for normal attempts and pair its tag with its commit."""
        if (self.baseline_tag is None) != (self.baseline_sha is None):
            raise ValueError(_BASELINE_PAIR_REQUIRED)
        if self.bootstrap == (self.baseline_tag is not None):
            raise ValueError(_BASELINE_TAG_REQUIRED)
        return self


class PublishedRelease(ImmutableRecord):
    """GitHub release listing facts used to select the completed baseline."""

    release_id: int
    tag_name: str
    is_draft: bool
    is_prerelease: bool
    published_at: datetime | None


def select_completed_release(releases: Iterable[PublishedRelease]) -> PublishedRelease:
    """Select the most recently published stable semantic release, independent of ancestry."""
    candidates = [
        release
        for release in releases
        if not release.is_draft
        and not release.is_prerelease
        and release.published_at is not None
        and _SEMANTIC_TAG_PATTERN.fullmatch(release.tag_name) is not None
    ]
    if not candidates:
        raise ValueError(_NO_COMPLETED_RELEASE)
    return max(candidates, key=lambda release: (release.published_at, release.release_id))


class ProviderAttempt(ImmutableRecord):
    """One provider execution, retaining typed failure and report identity."""

    provider: ProviderName
    outcome: ProviderOutcome
    failure: ProviderFailure | None
    report_sha256: str | None
    auth_settled: bool
    auth_settlement_failed: bool = False
    exit_code: int | None = None
    timed_out: bool = False
    diagnostic_path: str | None = None


class CandidateIdentity(ImmutableRecord):
    """Identity of the release candidate and the assessment it materializes."""

    attempt: AttemptIdentity
    version: str
    candidate_sha: str
    candidate_tree_sha: str
    assessment_sha256: str
    bundle_sha256: str | None


class ProofIdentity(ImmutableRecord):
    """Verification result bound to one exact candidate tree."""

    candidate_sha: str
    candidate_tree_sha: str
    lint_succeeded: bool
    installer_succeeded: bool
    evidence_sha256: str | None


class PublicationReceipt(ImmutableRecord):
    """Recoverable publication state tied to a proved candidate."""

    candidate: CandidateIdentity
    proof: ProofIdentity
    state: PublicationState
    tag: str
    github_release_id: str | None


def capture_attempt(
    repo: Repo,
    *,
    repository: str,
    workflow_run_id: str,
    workflow_run_attempt: int,
    baseline_tag: str | None,
    bootstrap: bool = False,
) -> AttemptIdentity:
    """Capture canonical main and validate an explicitly selected publication baseline."""
    source_sha = _resolve_commit(repo, _REMOTE_MAIN_COMMIT, _SOURCE_COMMIT_UNAVAILABLE)
    baseline_sha: str | None = None
    if baseline_tag is not None:
        baseline_sha = _resolve_commit(repo, baseline_tag, _BASELINE_COMMIT_UNAVAILABLE)
        try:
            repo.git.merge_base(_IS_ANCESTOR_ARGUMENT, baseline_sha, source_sha)
        except GitCommandError:
            raise ValueError(_BASELINE_NOT_ANCESTOR) from None
    return AttemptIdentity(
        repository=repository,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        source_sha=source_sha,
        baseline_tag=baseline_tag,
        baseline_sha=baseline_sha,
        bootstrap=bootstrap,
    )


def load_attempt_identity(path: Path) -> AttemptIdentity:
    """Load and strictly validate an attempt record transported between stages."""
    return AttemptIdentity.model_validate_json(path.read_text(encoding=_UTF8_ENCODING))


def validate_attempt_checkout(repo: Repo, attempt: AttemptIdentity) -> None:
    """Verify that a stage checkout and fetched tag match the captured attempt."""
    if repo.commit(_HEAD_REFERENCE).hexsha != attempt.source_sha:
        raise ValueError(_ATTEMPT_SOURCE_MISMATCH)
    if attempt.baseline_tag is None or attempt.baseline_sha is None:
        if not attempt.bootstrap:
            raise ValueError(_BASELINE_TAG_REQUIRED)
        return
    baseline_sha = _resolve_commit(repo, attempt.baseline_tag, _BASELINE_COMMIT_UNAVAILABLE)
    if baseline_sha != attempt.baseline_sha:
        raise ValueError(_ATTEMPT_BASELINE_MISMATCH)
    try:
        repo.git.merge_base(_IS_ANCESTOR_ARGUMENT, baseline_sha, attempt.source_sha)
    except GitCommandError:
        raise ValueError(_BASELINE_NOT_ANCESTOR) from None


def _resolve_commit(repo: Repo, reference: str, error_message: str) -> str:
    """Resolve one reference to a commit object id or return a contract error."""
    try:
        return str(repo.git.rev_parse(_VERIFY_ARGUMENT, reference + _COMMIT_SUFFIX)).strip()
    except GitCommandError:
        raise ValueError(error_message) from None
