"""Bound work publication observations, independent of integration delivery."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from teleclaude.types.github_binding import GitHubSessionBinding, GitHubWorkTarget
from teleclaude.types.github_posting import (
    GitHubAcceptance,
    GitHubObjectAssociation,
    GitHubObjectRef,
    GitHubPullRequestDescriptionMutation,
)

_SHA = r"^[0-9a-f]{40}$"
_DIGEST = r"^[0-9a-f]{64}$"
_DESCRIPTION_REQUIRED = "A PR description edit requires an explicit title or body"


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


class GitHubPullRequestOperation(StrEnum):
    """Only creating-builder description operations, without readiness or review effects."""

    CREATE = "create"
    EDIT = "edit"


class GitHubPullRequestCreateRequest(BaseModel):
    """Exact bound work scope plus explicitly collected artifact text."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    operation: Literal[GitHubPullRequestOperation.CREATE] = GitHubPullRequestOperation.CREATE
    target: GitHubWorkTarget
    title: str = Field(min_length=1)
    body: str


class GitHubPullRequestEditRequest(BaseModel):
    """One explicit provider number, title/body only; no native metadata or branch mutations."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    operation: Literal[GitHubPullRequestOperation.EDIT] = GitHubPullRequestOperation.EDIT
    target: GitHubWorkTarget
    number: int = Field(gt=0, strict=True)
    title: str | None = Field(default=None, min_length=1)
    body: str | None = None

    @model_validator(mode="after")
    def require_description(self) -> Self:
        if self.title is None and self.body is None:
            raise ValueError(_DESCRIPTION_REQUIRED)
        return self


class GitHubPullRequestSnapshot(BaseModel):
    """Verified provider observations; head is not a review or a workflow readiness assertion."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    object: GitHubObjectRef
    head_ref: str
    base_ref: str
    head_sha: str = Field(pattern=_SHA)
    title_digest: str = Field(pattern=_DIGEST)
    body_digest: str = Field(pattern=_DIGEST)
    state: Literal["open", "closed"]
    draft: bool
    url: str
    updated_at: str


class GitHubPullRequestStage(StrEnum):
    """Reads remain distinct from mutation acceptance and durable later attribution."""

    ADMISSION = "admission"
    DISCOVERY = "discovery"
    PREFLIGHT = "preflight"
    MUTATION = "mutation"
    ATTRIBUTION = "attribution"


class GitHubPullRequestFailure(StrEnum):
    """Unavailable owner evidence never selects another actor or supplies replay authority."""

    BUILDER = "current_builder_required"
    PARENT = "authoritative_driver_binding_unavailable"
    WORK_REF = "authoritative_branch_or_base_unavailable"
    PROOF = "current_session_push_proof_unavailable"
    CONTEXT = "context_changed"
    CREDENTIAL = "credential_refused"
    DISCOVERY = "complete_exact_branch_discovery_unavailable"
    CREATOR = "recorded_creating_session_unavailable_or_mismatched"
    PROVIDER = "provider_result_unverified"
    REFUSED = "provider_refused"
    UNKNOWN = "provider_acceptance_unknown"
    RETENTION = "association_retention_failed"
    CANCELLED = "cancelled"


class GitHubPullRequestResult(BaseModel):
    """Acceptance, available object facts and durable attribution are separate."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    operation: GitHubPullRequestOperation
    stage: GitHubPullRequestStage
    acceptance: GitHubAcceptance
    failure: GitHubPullRequestFailure | None = None
    object: GitHubObjectRef | None = None
    snapshot: GitHubPullRequestSnapshot | None = None
    association: GitHubObjectAssociation | None = None
    mutation: GitHubPullRequestDescriptionMutation | None = None
    reused: bool = False
    provider_status: int | None = None
    retry_after: timedelta | None = None
    credential_refusal: str | None = None

    @property
    def attributed(self) -> bool:
        return (
            self.failure is None
            and self.association is not None
            and self.object == self.association.object
            and (
                (self.reused and self.acceptance is GitHubAcceptance.NO_EFFECT)
                or (
                    self.acceptance is GitHubAcceptance.CONFIRMED
                    and (self.operation is GitHubPullRequestOperation.CREATE or self.mutation is not None)
                )
            )
        )
