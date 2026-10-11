"""Immutable identities and outcomes for one serialized release attempt."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from teleclaude.git import GitCommandError, Repo
from tools.ci.runtime_acceptance import validate_full_report_bytes

_REMOTE_MAIN_COMMIT = "refs/remotes/origin/main^{commit}"
_COMMIT_SUFFIX = "^{commit}"
_BASELINE_TAG_REQUIRED = "A normal release attempt requires a completed publication baseline."
_BASELINE_PAIR_REQUIRED = "Baseline tag and commit must either both be present or both be absent."
_BASELINE_NOT_ANCESTOR = "The completed publication baseline is not an ancestor of captured source."
_SOURCE_COMMIT_UNAVAILABLE = "Canonical origin/main did not resolve to a commit."
_BASELINE_COMMIT_UNAVAILABLE = "The completed publication tag did not resolve to a commit."
_NO_COMPLETED_RELEASE = "No completed semantic GitHub release is available as a baseline."
_MANUAL_VERSION_REQUIRED = "A manual release decision requires its explicit semantic version."
_AUTOMATIC_BASELINE_REQUIRED = "An automatic release decision requires a completed publication baseline."
_ATTEMPT_SOURCE_MISMATCH = "The checkout does not match the captured source revision."
_ATTEMPT_BASELINE_MISMATCH = "The completed publication tag does not match the captured baseline commit."
_UTF8_ENCODING = "utf-8"
_IS_ANCESTOR_ARGUMENT = "--is-ancestor"
_HEAD_REFERENCE = "HEAD"
_VERIFY_ARGUMENT = "--verify"
_SEMANTIC_VERSION_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
_LEGACY_BOOTSTRAP_MARKER = "bootstrap"
_VERSION_PREFIX = "v"
_VERSION_SEPARATOR = "."
_ATTEMPT_BOOTSTRAP_FIELD = "bootstrap"
_CANDIDATE_ATTEMPT_FIELD = "attempt"
_CANDIDATE_VERSION_FIELD = "version"
_CANDIDATE_ASSESSMENT_FIELD = "assessment_sha256"
_CANDIDATE_DECISION_DIGEST_FIELD = "decision_sha256"
_COMMIT_NOTES_DIGEST_FIELD = "commit_notes_sha256"
_DECISION_DIGEST_EXCLUDED_FIELDS = {_COMMIT_NOTES_DIGEST_FIELD}
_CANDIDATE_LEGACY_ASSESSMENT_FIELD = "legacy_assessment_sha256"
_CANDIDATE_LEGACY_RECORD_FIELD = "legacy_record_sha256"
_PROVENANCE_SCHEMA_FIELD = "schema_version"
_PROVENANCE_ATTEMPT_FIELD = "attempt"
_PROVENANCE_DECISION_MODE_FIELD = "decision_mode"
_PROVENANCE_VERSION_FIELD = "version"
_PROVENANCE_ASSESSMENT_FIELD = "assessment_sha256"
_PROVENANCE_LEGACY_ASSESSMENT_FIELD = "legacy_assessment_sha256"
_PROVENANCE_LEGACY_NOTES_FIELD = "bootstrap_notes_sha256"
_PROVENANCE_SELECTED_PROVIDER_FIELD = "selected_provider"
_PROVENANCE_DECISION_DIGEST_FIELD = "decision_sha256"
_PROVENANCE_LEGACY_RECORD_FIELD = "legacy_record_sha256"
_RECEIPT_PROOF_FIELD = "proof"
_RECEIPT_CANDIDATE_FIELD = "candidate"
_RECEIPT_LEGACY_RECORD_FIELD = "legacy_record_sha256"
_INVALID_ATTEMPT_RECORD = "The release attempt record is invalid."
_INVALID_CANDIDATE_RECORD = "The release candidate record is invalid."
_INVALID_PROVENANCE_RECORD = "The release provenance record is invalid."
_INVALID_RECEIPT_RECORD = "The publication receipt is invalid."
_INVALID_SEMANTIC_VERSION = "The release version must be a stable semantic version tag."
_INVALID_OPERATOR_VERSION = "The supplied release version must be a stable semantic version."
_INVALID_DECISION = "The release decision record is invalid."
_JSON_SORT_KEYS = True
_JSON_SEPARATORS = (",", ":")
_JSON_MODE = "json"


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


class ReleaseDecisionMode(StrEnum):
    """Authority that selected a release version, independent of baseline state."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"


class ImmutableRecord(BaseModel):
    """Base contract for strict, immutable release records."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class LegacyAttemptIdentity(ImmutableRecord):
    """Historical attempt shape accepted only by the migration boundary."""

    repository: str
    workflow_run_id: str
    workflow_run_attempt: int
    source_sha: str
    baseline_tag: str | None
    baseline_sha: str | None
    bootstrap: bool


class AttemptIdentity(ImmutableRecord):
    """Source, baseline, and workflow identity captured after serialization."""

    repository: str
    workflow_run_id: str
    workflow_run_attempt: int
    source_sha: str
    baseline_tag: str | None
    baseline_sha: str | None
    decision_mode: ReleaseDecisionMode
    requested_version: str | None = None
    legacy_baseline_marker: str | None = None

    @model_validator(mode="after")
    def validate_baseline_pair(self) -> AttemptIdentity:
        """Require a baseline for automatic attempts and pair its tag with its commit."""
        if (self.baseline_tag is None) != (self.baseline_sha is None):
            raise ValueError(_BASELINE_PAIR_REQUIRED)
        if self.decision_mode == ReleaseDecisionMode.AUTOMATIC and self.baseline_tag is None:
            raise ValueError(_AUTOMATIC_BASELINE_REQUIRED)
        if self.decision_mode == ReleaseDecisionMode.AUTOMATIC and self.requested_version is not None:
            raise ValueError(_BASELINE_TAG_REQUIRED)
        if self.decision_mode == ReleaseDecisionMode.MANUAL and self.requested_version is None:
            if self.legacy_baseline_marker != _LEGACY_BOOTSTRAP_MARKER:
                raise ValueError(_MANUAL_VERSION_REQUIRED)
        if self.requested_version is not None:
            validate_stable_version(self.requested_version)
        if self.legacy_baseline_marker is not None and self.legacy_baseline_marker != _LEGACY_BOOTSTRAP_MARKER:
            raise ValueError(_BASELINE_TAG_REQUIRED)
        if self.legacy_baseline_marker is not None and (
            self.decision_mode != ReleaseDecisionMode.MANUAL or self.baseline_tag is not None
        ):
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
        and is_stable_version_tag(release.tag_name)
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
    assessment_sha256: str | None
    decision_sha256: str
    commit_notes_sha256: str | None = None
    legacy_assessment_sha256: str | None = None
    legacy_record_sha256: str | None = None
    bundle_sha256: str | None


class ReleaseDecision(ImmutableRecord):
    """Captured version authority and the assessment, when automation selected it."""

    mode: ReleaseDecisionMode
    version: str
    source_sha: str
    workflow_run_id: str
    workflow_run_attempt: int
    assessment_sha256: str | None
    commit_notes_sha256: str | None = None
    legacy_assessment_sha256: str | None = None
    legacy_baseline_marker: str | None = None
    legacy_record_sha256: str | None = None

    @model_validator(mode="after")
    def validate_authority(self) -> ReleaseDecision:
        """Keep manual version authority distinct from an automated assessment."""
        validate_stable_version(self.version)
        if self.mode == ReleaseDecisionMode.MANUAL:
            if self.assessment_sha256 is not None:
                raise ValueError(_INVALID_DECISION)
        elif self.assessment_sha256 is None or self.legacy_assessment_sha256 is not None:
            raise ValueError(_INVALID_DECISION)
        if self.legacy_baseline_marker not in {None, _LEGACY_BOOTSTRAP_MARKER}:
            raise ValueError(_INVALID_DECISION)
        if self.legacy_record_sha256 is not None and _SHA256_PATTERN.fullmatch(self.legacy_record_sha256) is None:
            raise ValueError(_INVALID_DECISION)
        if self.commit_notes_sha256 is not None and _SHA256_PATTERN.fullmatch(self.commit_notes_sha256) is None:
            raise ValueError(_INVALID_DECISION)
        return self


class ProofIdentity(ImmutableRecord):
    """Verification result bound to one exact candidate tree."""

    candidate_sha: str
    candidate_tree_sha: str
    lint_succeeded: bool
    installer_succeeded: bool
    evidence_sha256: str | None
    runtime_acceptance_succeeded: bool = False
    runtime_acceptance_report_sha256: str | None = None


class PublicationReceipt(ImmutableRecord):
    """Recoverable publication state tied to a proved candidate."""

    candidate: CandidateIdentity
    proof: ProofIdentity
    state: PublicationState
    tag: str
    github_release_id: str | None
    legacy_record_sha256: str | None = None


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MAX_RUNTIME_REPORT_BYTES = 8 * 1024 * 1024
_MAX_CANDIDATE_CHECK_BYTES = 64 * 1024


def validate_runtime_acceptance_evidence(
    candidate: CandidateIdentity,
    proof: ProofIdentity | None,
    candidate_check_data: bytes,
    report_data: bytes,
) -> str:
    """Validate the candidate check and full report, returning the report digest."""
    try:
        if len(candidate_check_data) > _MAX_CANDIDATE_CHECK_BYTES or len(report_data) > _MAX_RUNTIME_REPORT_BYTES:
            raise ValueError
        candidate_check = json.loads(candidate_check_data)
        report_digest = hashlib.sha256(report_data).hexdigest()
        if (
            not isinstance(candidate_check, dict)
            or set(candidate_check)
            != {
                "candidate_sha",
                "candidate_tree_sha",
                "lint_succeeded",
                "lint_log_sha256",
                "runtime_acceptance_succeeded",
                "runtime_acceptance_report_sha256",
            }
            or candidate_check["candidate_sha"] != candidate.candidate_sha
            or candidate_check["candidate_tree_sha"] != candidate.candidate_tree_sha
            or candidate_check["lint_succeeded"] is not True
            or not isinstance(candidate_check["lint_log_sha256"], str)
            or _SHA256_PATTERN.fullmatch(candidate_check["lint_log_sha256"]) is None
            or candidate_check["runtime_acceptance_succeeded"] is not True
            or candidate_check["runtime_acceptance_report_sha256"] != report_digest
        ):
            raise ValueError
        validate_full_report_bytes(
            report_data,
            source_revision=candidate.candidate_sha,
            source_tree=candidate.candidate_tree_sha,
        )
        if proof is not None and (
            not proof.runtime_acceptance_succeeded or proof.runtime_acceptance_report_sha256 != report_digest
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError(
            "Full runtime acceptance is missing, incomplete, or mismatched; rerun acceptance and installer proof "
            "against the original candidate."
        ) from None
    return report_digest


def load_proof_identity(data: bytes) -> ProofIdentity:
    """Forward-migrate a standalone proof, treating pre-acceptance proofs as absent evidence."""
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("The release proof record is invalid.")
    payload.setdefault("runtime_acceptance_succeeded", False)
    payload.setdefault("runtime_acceptance_report_sha256", None)
    return ProofIdentity.model_validate(payload)


def validate_stable_version(version: str) -> str:
    """Require one canonical stable semantic version tag."""
    if not is_stable_version_tag(version):
        raise ValueError(_INVALID_SEMANTIC_VERSION)
    return version


def is_stable_version_tag(version: str) -> bool:
    """Return whether a tag uses the canonical stable semantic version shape."""
    return (
        version.startswith(_VERSION_PREFIX)
        and _SEMANTIC_VERSION_PATTERN.fullmatch(version.removeprefix(_VERSION_PREFIX)) is not None
    )


def normalize_stable_version(version: str) -> str:
    """Canonicalize a stable semantic version to its release-tag form."""
    canonical = version if version.startswith(_VERSION_PREFIX) else _VERSION_PREFIX + version
    try:
        return validate_stable_version(canonical)
    except ValueError:
        raise ValueError(_INVALID_OPERATOR_VERSION) from None


def stable_version_components(version: str) -> tuple[int, int, int]:
    """Parse the numeric components of a canonical stable release tag."""
    validate_stable_version(version)
    major, minor, patch = version.removeprefix(_VERSION_PREFIX).split(_VERSION_SEPARATOR)
    return int(major), int(minor), int(patch)


def stable_version_is_newer(version: str, baseline: str) -> bool:
    """Compare stable release tags by their numeric semantic-version components."""
    return stable_version_components(version) > stable_version_components(baseline)


def _normalize_attempt_payload(payload: object, *, version: str | None = None) -> AttemptIdentity:
    """Migrate the historical bootstrap flag once before strict attempt parsing."""
    if not isinstance(payload, dict):
        raise ValueError(_INVALID_ATTEMPT_RECORD)
    if _ATTEMPT_BOOTSTRAP_FIELD not in payload:
        return AttemptIdentity.model_validate_json(json.dumps(payload))
    legacy = LegacyAttemptIdentity.model_validate_json(json.dumps(payload))
    is_legacy_manual = legacy.bootstrap
    return AttemptIdentity(
        repository=legacy.repository,
        workflow_run_id=legacy.workflow_run_id,
        workflow_run_attempt=legacy.workflow_run_attempt,
        source_sha=legacy.source_sha,
        baseline_tag=legacy.baseline_tag,
        baseline_sha=legacy.baseline_sha,
        decision_mode=ReleaseDecisionMode.MANUAL if is_legacy_manual else ReleaseDecisionMode.AUTOMATIC,
        requested_version=version if is_legacy_manual else None,
        legacy_baseline_marker=_LEGACY_BOOTSTRAP_MARKER if is_legacy_manual else None,
    )


def load_attempt_identity_bytes(data: bytes) -> AttemptIdentity:
    """Load a current or historical standalone attempt at the record boundary."""
    return _normalize_attempt_payload(json.loads(data))


def release_decision_digest(
    attempt: AttemptIdentity,
    version: str,
    assessment_sha256: str | None,
    legacy_assessment_sha256: str | None,
) -> str:
    """Hash the normalized release decision without synthesizing a report."""
    decision = ReleaseDecision(
        mode=attempt.decision_mode,
        version=version,
        source_sha=attempt.source_sha,
        workflow_run_id=attempt.workflow_run_id,
        workflow_run_attempt=attempt.workflow_run_attempt,
        assessment_sha256=assessment_sha256,
        legacy_assessment_sha256=legacy_assessment_sha256,
        legacy_baseline_marker=attempt.legacy_baseline_marker,
    )
    # The commit-note digest belongs to the frozen artifact identity, not the
    # decision authority. Keep the authority serialization stable for records
    # written before note identity was introduced.
    decision_payload = decision.model_dump(mode=_JSON_MODE, exclude=_DECISION_DIGEST_EXCLUDED_FIELDS)
    return hashlib.sha256(json.dumps(decision_payload, separators=_JSON_SEPARATORS).encode(_UTF8_ENCODING)).hexdigest()


def load_candidate_identity(data: bytes) -> CandidateIdentity:
    """Normalize candidate and nested legacy attempt records before strict use."""
    payload = json.loads(data)
    if not isinstance(payload, dict) or not isinstance(payload.get(_CANDIDATE_ATTEMPT_FIELD), dict):
        raise ValueError(_INVALID_CANDIDATE_RECORD)
    version = payload.get(_CANDIDATE_VERSION_FIELD)
    if not isinstance(version, str):
        raise ValueError(_INVALID_CANDIDATE_RECORD)
    validate_stable_version(version)
    attempt = _normalize_attempt_payload(payload[_CANDIDATE_ATTEMPT_FIELD], version=version)
    normalized = dict(payload)
    normalized[_CANDIDATE_ATTEMPT_FIELD] = attempt
    if attempt.decision_mode == ReleaseDecisionMode.MANUAL and attempt.requested_version not in {None, version}:
        raise ValueError(_INVALID_CANDIDATE_RECORD)
    assessment = normalized.get(_CANDIDATE_ASSESSMENT_FIELD)
    if assessment is not None and (not isinstance(assessment, str) or _SHA256_PATTERN.fullmatch(assessment) is None):
        raise ValueError(_INVALID_CANDIDATE_RECORD)
    notes_digest = normalized.get(_COMMIT_NOTES_DIGEST_FIELD)
    if notes_digest is not None and (
        not isinstance(notes_digest, str) or _SHA256_PATTERN.fullmatch(notes_digest) is None
    ):
        raise ValueError(_INVALID_CANDIDATE_RECORD)
    legacy_assessment: str | None = normalized.get(_CANDIDATE_LEGACY_ASSESSMENT_FIELD)
    if _CANDIDATE_DECISION_DIGEST_FIELD not in normalized:
        legacy_assessment = assessment if attempt.decision_mode == ReleaseDecisionMode.MANUAL else None
        current_assessment = assessment if attempt.decision_mode == ReleaseDecisionMode.AUTOMATIC else None
        normalized[_CANDIDATE_ASSESSMENT_FIELD] = current_assessment
        normalized[_CANDIDATE_LEGACY_ASSESSMENT_FIELD] = legacy_assessment
        normalized[_CANDIDATE_DECISION_DIGEST_FIELD] = release_decision_digest(
            attempt,
            version,
            current_assessment,
            legacy_assessment,
        )
        normalized[_CANDIDATE_LEGACY_RECORD_FIELD] = hashlib.sha256(
            json.dumps(payload, sort_keys=_JSON_SORT_KEYS, separators=_JSON_SEPARATORS).encode(_UTF8_ENCODING)
        ).hexdigest()
    else:
        expected_decision_digest = release_decision_digest(
            attempt,
            version,
            assessment,
            legacy_assessment,
        )
        if normalized[_CANDIDATE_DECISION_DIGEST_FIELD] != expected_decision_digest:
            raise ValueError(_INVALID_CANDIDATE_RECORD)
    return CandidateIdentity.model_validate(normalized)


def load_release_provenance(data: bytes, version: str) -> ReleaseDecision:
    """Normalize retained provenance while preserving its original record digest."""
    validate_stable_version(version)
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError(_INVALID_PROVENANCE_RECORD)
    schema_version = payload.get(_PROVENANCE_SCHEMA_FIELD)
    attempt_payload = payload.get(_PROVENANCE_ATTEMPT_FIELD)
    if not isinstance(attempt_payload, dict):
        raise ValueError(_INVALID_PROVENANCE_RECORD)
    attempt = _normalize_attempt_payload(attempt_payload, version=version)
    if schema_version == 1:
        old_assessment = payload.get(_PROVENANCE_ASSESSMENT_FIELD)
        if not isinstance(old_assessment, str) or _SHA256_PATTERN.fullmatch(old_assessment) is None:
            raise ValueError(_INVALID_PROVENANCE_RECORD)
        is_manual = attempt.decision_mode == ReleaseDecisionMode.MANUAL
        legacy_notes = payload.get(_PROVENANCE_LEGACY_NOTES_FIELD)
        if legacy_notes is not None and (
            not isinstance(legacy_notes, str) or _SHA256_PATTERN.fullmatch(legacy_notes) is None
        ):
            raise ValueError(_INVALID_PROVENANCE_RECORD)
        legacy_assessment = (legacy_notes if isinstance(legacy_notes, str) else old_assessment) if is_manual else None
        assessment = None if is_manual else old_assessment
        selected_provider = payload.get(_PROVENANCE_SELECTED_PROVIDER_FIELD)
        if is_manual:
            if selected_provider != _LEGACY_BOOTSTRAP_MARKER:
                raise ValueError(_INVALID_PROVENANCE_RECORD)
        elif selected_provider not in {member.value for member in ProviderName}:
            raise ValueError(_INVALID_PROVENANCE_RECORD)
        return ReleaseDecision(
            mode=attempt.decision_mode,
            version=version,
            source_sha=attempt.source_sha,
            workflow_run_id=attempt.workflow_run_id,
            workflow_run_attempt=attempt.workflow_run_attempt,
            assessment_sha256=assessment,
            commit_notes_sha256=None,
            legacy_assessment_sha256=legacy_assessment,
            legacy_baseline_marker=attempt.legacy_baseline_marker,
            legacy_record_sha256=hashlib.sha256(data).hexdigest(),
        )
    if schema_version != 2 or payload.get(_PROVENANCE_VERSION_FIELD) != version:
        raise ValueError(_INVALID_PROVENANCE_RECORD)
    if payload.get(_PROVENANCE_DECISION_MODE_FIELD) != attempt.decision_mode.value:
        raise ValueError(_INVALID_PROVENANCE_RECORD)
    if attempt.decision_mode == ReleaseDecisionMode.MANUAL:
        if (
            attempt.requested_version not in {None, version}
            or payload.get(_PROVENANCE_SELECTED_PROVIDER_FIELD) is not None
        ):
            raise ValueError(_INVALID_PROVENANCE_RECORD)
    elif payload.get(_PROVENANCE_SELECTED_PROVIDER_FIELD) not in {member.value for member in ProviderName}:
        raise ValueError(_INVALID_PROVENANCE_RECORD)
    assessment_value = payload.get(_PROVENANCE_ASSESSMENT_FIELD)
    notes_digest = payload.get(_COMMIT_NOTES_DIGEST_FIELD)
    if notes_digest is not None and (
        not isinstance(notes_digest, str) or _SHA256_PATTERN.fullmatch(notes_digest) is None
    ):
        raise ValueError(_INVALID_PROVENANCE_RECORD)
    legacy_assessment_value = payload.get(_PROVENANCE_LEGACY_ASSESSMENT_FIELD)
    if assessment_value is not None and (
        not isinstance(assessment_value, str) or _SHA256_PATTERN.fullmatch(assessment_value) is None
    ):
        raise ValueError(_INVALID_PROVENANCE_RECORD)
    if legacy_assessment_value is not None and (
        not isinstance(legacy_assessment_value, str) or _SHA256_PATTERN.fullmatch(legacy_assessment_value) is None
    ):
        raise ValueError(_INVALID_PROVENANCE_RECORD)
    if (attempt.decision_mode == ReleaseDecisionMode.AUTOMATIC) != (assessment_value is not None):
        raise ValueError(_INVALID_PROVENANCE_RECORD)
    expected_digest = release_decision_digest(
        attempt,
        version,
        assessment_value,
        legacy_assessment_value,
    )
    if payload.get(_PROVENANCE_DECISION_DIGEST_FIELD) != expected_digest:
        raise ValueError(_INVALID_PROVENANCE_RECORD)
    legacy_record_digest = payload.get(_PROVENANCE_LEGACY_RECORD_FIELD)
    if legacy_record_digest is not None and (
        not isinstance(legacy_record_digest, str) or _SHA256_PATTERN.fullmatch(legacy_record_digest) is None
    ):
        raise ValueError(_INVALID_PROVENANCE_RECORD)
    return ReleaseDecision(
        mode=attempt.decision_mode,
        version=version,
        source_sha=attempt.source_sha,
        workflow_run_id=attempt.workflow_run_id,
        workflow_run_attempt=attempt.workflow_run_attempt,
        assessment_sha256=assessment_value,
        commit_notes_sha256=notes_digest,
        legacy_assessment_sha256=legacy_assessment_value,
        legacy_baseline_marker=attempt.legacy_baseline_marker,
        legacy_record_sha256=legacy_record_digest,
    )


def load_publication_receipt(data: bytes) -> PublicationReceipt:
    """Forward-migrate a receipt and nested records at the single compatibility boundary."""
    payload = json.loads(data)
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get(_RECEIPT_PROOF_FIELD), dict)
        or not isinstance(payload.get(_RECEIPT_CANDIDATE_FIELD), dict)
    ):
        raise ValueError(_INVALID_RECEIPT_RECORD)
    normalized = dict(payload)
    candidate_data = json.dumps(payload[_RECEIPT_CANDIDATE_FIELD]).encode(_UTF8_ENCODING)
    proof_data = json.dumps(payload[_RECEIPT_PROOF_FIELD]).encode(_UTF8_ENCODING)
    normalized[_RECEIPT_CANDIDATE_FIELD] = load_candidate_identity(candidate_data).model_dump(mode=_JSON_MODE)
    normalized[_RECEIPT_PROOF_FIELD] = load_proof_identity(proof_data).model_dump(mode=_JSON_MODE)
    normalized.setdefault(_RECEIPT_LEGACY_RECORD_FIELD, hashlib.sha256(data).hexdigest())
    return PublicationReceipt.model_validate_json(json.dumps(normalized))


def capture_attempt(
    repo: Repo,
    *,
    repository: str,
    workflow_run_id: str,
    workflow_run_attempt: int,
    baseline_tag: str | None,
    decision_mode: ReleaseDecisionMode = ReleaseDecisionMode.AUTOMATIC,
    requested_version: str | None = None,
    legacy_baseline_marker: str | None = None,
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
        decision_mode=decision_mode,
        requested_version=requested_version,
        legacy_baseline_marker=legacy_baseline_marker,
    )


def load_attempt_identity(path: Path) -> AttemptIdentity:
    """Load and strictly validate an attempt record transported between stages."""
    return load_attempt_identity_bytes(path.read_bytes())


def validate_attempt_checkout(repo: Repo, attempt: AttemptIdentity) -> None:
    """Verify that a stage checkout and fetched tag match the captured attempt."""
    if repo.commit(_HEAD_REFERENCE).hexsha != attempt.source_sha:
        raise ValueError(_ATTEMPT_SOURCE_MISMATCH)
    if attempt.baseline_tag is None or attempt.baseline_sha is None:
        if attempt.decision_mode != ReleaseDecisionMode.MANUAL:
            raise ValueError(_AUTOMATIC_BASELINE_REQUIRED)
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
