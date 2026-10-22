"""Bound work publication observations, independent of integration delivery."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from teleclaude.types.github_binding import GitHubSessionBinding, GitHubWorkTarget

_SHA = r"^[0-9a-f]{40}$"


class GitHubBranchPublicationRequest(BaseModel):
    """Owner-supplied scope; actual Git state only corroborates these values."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    target: GitHubWorkTarget
    worktree: Path
    branch: str = Field(min_length=1)
    head_sha: str = Field(pattern=_SHA)
    base: str = Field(min_length=1)


class GitHubPushActivityType(StrEnum):
    """Provider transitions eligible to corroborate an actual work-ref update."""

    PUSH = "push"
    FORCE_PUSH = "force_push"
    BRANCH_CREATION = "branch_creation"


class GitHubPushProof(BaseModel):
    """Actual confined-child update plus observed provider corroboration, not a causal event receipt."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    binding: GitHubSessionBinding
    target: GitHubWorkTarget
    ref: str
    before: str = Field(pattern=_SHA)
    after: str = Field(pattern=_SHA)
    activity_id: int = Field(gt=0, strict=True)
    activity_node_id: str = Field(min_length=1)
    activity_type: GitHubPushActivityType
    activity_at: AwareDatetime
    observed_at: AwareDatetime


class GitHubPublicationState(StrEnum):
    """Only a durably retained confirmed update authorizes a subsequent first PR."""

    REFUSED = "refused"
    NOOP = "noop"
    UNKNOWN = "unknown"
    CONFIRMED = "confirmed"


class GitHubPublicationFailure(StrEnum):
    """Safe failure vocabulary without child diagnostics or credential-bearing requests."""

    CONTEXT = "context_unavailable"
    WORK_REF = "authoritative_work_ref_or_base_unavailable"
    HISTORY = "source_history_unavailable"
    CREDENTIAL = "credential_refused"
    OBSERVATION = "provider_observation_incomplete"
    TRACKING = "tracking_expectation_changed"
    SEND = "update_unverified"
    ATTRIBUTION = "actor_or_transition_unverified"
    RETENTION = "proof_retention_failed"
    CANCELLED = "cancelled"


class GitHubPublicationResult(BaseModel):
    """Known ref facts survive partial outcomes; no result grants retry permission."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    state: GitHubPublicationState
    failure: GitHubPublicationFailure | None = None
    before: str | None = None
    desired: str | None = None
    current: str | None = None
    before_observed: bool = False
    current_observed: bool = False
    child_update_acknowledged: bool = False
    possible_remote_effect: bool = False
    proof: GitHubPushProof | None = None
    corroboration: GitHubPushProof | None = None
    tracking_advanced: bool | None = None
    provider_status: int | None = None
    retry_after_seconds: float | None = None
