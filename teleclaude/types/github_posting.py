"""Posting-source, provider acceptance and immutable attribution facts."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from teleclaude.core.roles import RoleName
from teleclaude.types.github_account import GitHubAccount
from teleclaude.types.github_binding import GitHubWorkTarget
from teleclaude.types.workflow_record import Act, Phase

_SOURCE_DISCRIMINATOR = "kind"
_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_COMMIT_PATTERN = r"^[0-9a-f]{40}$"
_PR_CREATION_INVALID = "PR creation requires its own coordinates and no reviewed SHA"
_MIRROR_ORDER_INVALID = "Mirror part must be within its source-owned total"
_REVIEW_HEAD_REQUIRED = "A review association requires the exact reviewed SHA"
_NATIVE_NOTE_REQUIRED = "Native context requires the canonical note act and no inferred phase"
_MAINTENANCE_TARGET_INVALID = "Maintenance requires the exact bound issue comment"
_PRODUCER_INVALID = "Qualified producer facts must be complete and match the accepted object target"
_MUTATION_EVIDENCE_INVALID = "Maintenance evidence must match its confirmed provider operation"


class GitHubPostSourceKind(StrEnum):
    """Trusted transport origin, separate from the lifecycle act vocabulary."""

    NATIVE = "native"
    SEALED = "sealed"
    REFLECTION = "reflection"


class NativeGitHubPostSource(BaseModel):
    """Native context has no source delivery/invocation identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal[GitHubPostSourceKind.NATIVE] = GitHubPostSourceKind.NATIVE


class SealedGitHubPostSource(BaseModel):
    """An invocation identity supplied by its sealed operation owner."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal[GitHubPostSourceKind.SEALED] = GitHubPostSourceKind.SEALED
    identity: str = Field(min_length=1)


class GitHubMirrorPart(BaseModel):
    """Source-owned mirror ordering; no sequence or identity is minted here."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    turn_id: str = Field(min_length=1)
    part: int = Field(gt=0, strict=True)
    total: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        """Keep the part within its owner's declared total."""
        if self.part > self.total:
            raise ValueError(_MIRROR_ORDER_INVALID)
        return self


class ReflectedGitHubPostSource(BaseModel):
    """A source event delivery and optional mirror part supplied by its owner."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal[GitHubPostSourceKind.REFLECTION] = GitHubPostSourceKind.REFLECTION
    identity: str = Field(min_length=1)
    mirror: GitHubMirrorPart | None = None


GitHubPostSource = Annotated[
    NativeGitHubPostSource | SealedGitHubPostSource | ReflectedGitHubPostSource,
    Field(discriminator=_SOURCE_DISCRIMINATOR),
]


class GitHubIssueCommentRequest(BaseModel):
    """One owner-admitted body-only append, never an arbitrary API request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target: GitHubWorkTarget
    body: str
    act: Act
    phase: Phase | None = None
    source: GitHubPostSource
    pr_scope: GitHubObjectRef | None = None

    @model_validator(mode="after")
    def require_native_context(self) -> Self:
        """A native request cannot manufacture a lifecycle act or phase."""
        if isinstance(self.source, NativeGitHubPostSource) and (self.act is not Act.NOTE or self.phase is not None):
            raise ValueError(_NATIVE_NOTE_REQUIRED)
        if self.pr_scope is not None and (
            not isinstance(self.source, NativeGitHubPostSource)
            or self.pr_scope.kind is not GitHubObjectKind.PULL_REQUEST
            or self.pr_scope.repository_id != self.target.repository_id
        ):
            raise ValueError(_MAINTENANCE_TARGET_INVALID)
        return self


class GitHubObjectKind(StrEnum):
    """Provider object namespaces whose numeric identifiers may overlap."""

    ISSUE_COMMENT = "issue_comment"
    REVIEW = "review"
    REVIEW_COMMENT = "review_comment"
    ISSUE_BODY = "issue_body"
    PULL_REQUEST = "pull_request"


class GitHubObjectRef(BaseModel):
    """Exact repository/container/object identity, with no text-based selector."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    repository_id: int = Field(gt=0, strict=True)
    container_number: int = Field(gt=0, strict=True)
    kind: GitHubObjectKind
    provider_id: int = Field(gt=0, strict=True)


class GitHubEditEvidence(BaseModel):
    """Available provider observations, without an edit-history completeness claim."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    updated_at: str | None = None
    revision_id: str | None = None
    last_editor: GitHubAccount | None = None


class GitHubPullRequestCreation(BaseModel):
    """Observed PR creation coordinates, distinct from a review's reviewed commit."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    head_ref: str = Field(min_length=1)
    base_ref: str = Field(min_length=1)
    head_sha: str = Field(pattern=_COMMIT_PATTERN)
    title_digest: str = Field(pattern=_DIGEST_PATTERN)


class GitHubReviewCommentPlacement(BaseModel):
    """Actual reply placement observations, never a COMMENT review's reviewed-SHA authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    in_reply_to_id: int = Field(gt=0, strict=True)
    commit_id: str = Field(min_length=1)
    original_commit_id: str = Field(min_length=1)
    review_id: int | None = Field(default=None, gt=0, strict=True)
    path: str
    line: int | None = None
    original_line: int | None = None
    start_line: int | None = None
    original_start_line: int | None = None
    side: Literal["LEFT", "RIGHT"] | None = None
    start_side: Literal["LEFT", "RIGHT"] | None = None


class GitHubObjectAssociation(BaseModel):
    """Immutable creation attribution recorded after verified provider acceptance."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    object: GitHubObjectRef
    work_issue_number: int = Field(gt=0, strict=True)
    session_id: str = Field(min_length=1)
    role: RoleName
    actor: GitHubAccount
    source: GitHubPostSource
    body_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    reviewed_sha: str | None = Field(default=None, min_length=1)
    edit_evidence: GitHubEditEvidence | None = None
    pull_request: GitHubPullRequestCreation | None = None
    review_comment: GitHubReviewCommentPlacement | None = None
    producer_principal: str | None = Field(default=None, min_length=1)
    producer_computer: str | None = Field(default=None, min_length=1)
    producer_target: GitHubWorkTarget | None = None

    @model_validator(mode="after")
    def require_review_head(self) -> Self:
        """Keep a review's actual head separate from its prose and source identity."""
        if self.object.kind is GitHubObjectKind.REVIEW and self.reviewed_sha is None:
            raise ValueError(_REVIEW_HEAD_REQUIRED)
        if (self.object.kind is GitHubObjectKind.PULL_REQUEST) != (self.pull_request is not None):
            raise ValueError(_PR_CREATION_INVALID)
        if self.pull_request is not None and (self.reviewed_sha is not None or self.body_digest is None):
            raise ValueError(_PR_CREATION_INVALID)
        if self.review_comment is not None and (
            self.object.kind is not GitHubObjectKind.REVIEW_COMMENT or self.reviewed_sha is not None
        ):
            raise ValueError(_MAINTENANCE_TARGET_INVALID)
        if (
            self.object.kind is GitHubObjectKind.REVIEW_COMMENT
            and isinstance(self.source, NativeGitHubPostSource)
            and (self.review_comment is None or self.reviewed_sha is not None)
        ):
            raise ValueError(_MAINTENANCE_TARGET_INVALID)
        qualified = (self.producer_principal, self.producer_computer, self.producer_target)
        if any(value is not None for value in qualified) and (
            any(value is None for value in qualified)
            or self.producer_target is None
            or self.producer_target.repository_id != self.object.repository_id
            or self.producer_target.issue_number != self.work_issue_number
        ):
            raise ValueError(_PRODUCER_INVALID)
        return self

    def same_creation(self, other: GitHubObjectAssociation) -> bool:
        """Compare immutable producing facts without treating a login spelling as identity."""
        return (
            self.object == other.object
            and self.work_issue_number == other.work_issue_number
            and self.session_id == other.session_id
            and self.role is other.role
            and self.actor.same_account(other.actor)
            and self.source == other.source
            and self.body_digest == other.body_digest
            and self.reviewed_sha == other.reviewed_sha
            and self.pull_request == other.pull_request
            and self.review_comment == other.review_comment
            and self.producer_principal == other.producer_principal
            and self.producer_computer == other.producer_computer
            and self.producer_target == other.producer_target
        )


class GitHubAcceptance(StrEnum):
    """Provider acceptance, independent of successful durable attribution."""

    CONFIRMED = "confirmed"
    NO_EFFECT = "no_effect"
    UNKNOWN = "unknown"


class GitHubPostFailure(StrEnum):
    """Non-sensitive terminal reasons, carrying no safe-retry inference."""

    ADMISSION_REFUSED = "admission_refused"
    SEND_UNCERTAIN = "send_uncertain"
    ACTOR_MISMATCH = "actor_mismatch"
    RESULT_UNVERIFIED = "result_unverified"
    ASSOCIATION_FAILED = "association_failed"
    CREDENTIAL_REFUSED = "credential_refused"
    BINARY_UNAVAILABLE = "binary_unavailable"
    PROVIDER_REFUSED = "provider_refused"
    PREFLIGHT_FAILED = "preflight_failed"
    CANCELLED = "cancelled"


class GitHubPostResult(BaseModel):
    """Send evidence plus durable attribution; unknown acceptance is not retry advice."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    acceptance: GitHubAcceptance
    object: GitHubObjectRef | None = None
    association: GitHubObjectAssociation | None = None
    failure: GitHubPostFailure | None = None
    body_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    edit_evidence: GitHubEditEvidence | None = None
    reviewed_sha: str | None = Field(default=None, min_length=1)
    review_comment: GitHubReviewCommentPlacement | None = None
    provider_status: int | None = Field(default=None, ge=100, le=599)
    retry_after: timedelta | None = None
    credential_refusal: str | None = None

    @property
    def attributed(self) -> bool:
        """Report completion from the posting owner's recorded-association result."""
        return (
            self.acceptance is GitHubAcceptance.CONFIRMED
            and self.failure is None
            and self.association is not None
            and self.object == self.association.object
        )


def _maintenance_target(target: GitHubWorkTarget, ref: GitHubObjectRef, pr_scope: GitHubObjectRef | None) -> None:
    container = target.issue_number
    if pr_scope is not None:
        if pr_scope.kind is not GitHubObjectKind.PULL_REQUEST or pr_scope.repository_id != target.repository_id:
            raise ValueError(_MAINTENANCE_TARGET_INVALID)
        container = pr_scope.container_number
    if (
        ref.kind not in (GitHubObjectKind.ISSUE_COMMENT, GitHubObjectKind.REVIEW_COMMENT)
        or (ref.kind is GitHubObjectKind.REVIEW_COMMENT and pr_scope is None)
        or ref.repository_id != target.repository_id
        or ref.container_number != container
    ):
        raise ValueError(_MAINTENANCE_TARGET_INVALID)


class GitHubIssueCommentEditRequest(BaseModel):
    """A body-only replacement of one explicit bound comment, with no actor/source selector."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    target: GitHubWorkTarget
    object: GitHubObjectRef
    body: str
    pr_scope: GitHubObjectRef | None = None

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        """Keep the object in the owning request's exact namespace."""
        _maintenance_target(self.target, self.object, self.pr_scope)
        return self


class GitHubIssueCommentDeleteRequest(BaseModel):
    """Deletion of one explicit bound comment, without a payload or implicit selection."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    target: GitHubWorkTarget
    object: GitHubObjectRef
    pr_scope: GitHubObjectRef | None = None

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        """Keep the object in the owning request's exact namespace."""
        _maintenance_target(self.target, self.object, self.pr_scope)
        return self


def _require_pr_scope(target: GitHubWorkTarget, scope: GitHubObjectRef) -> None:
    if scope.kind is not GitHubObjectKind.PULL_REQUEST or scope.repository_id != target.repository_id:
        raise ValueError(_MAINTENANCE_TARGET_INVALID)


class GitHubReviewRequest(BaseModel):
    """One native COMMENT review of an explicitly associated PR; no event or SHA selector."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    target: GitHubWorkTarget
    pr_scope: GitHubObjectRef
    body: str

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        """The provider read supplies the reviewed SHA after structural admission."""
        _require_pr_scope(self.target, self.pr_scope)
        return self


class GitHubReviewReplyRequest(BaseModel):
    """One body-only native reply to an explicit provider top-level review comment."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    target: GitHubWorkTarget
    pr_scope: GitHubObjectRef
    root_id: int = Field(gt=0, strict=True)
    body: str

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        """A reply target is a PR relationship candidate, not independently supplied authority."""
        _require_pr_scope(self.target, self.pr_scope)
        return self


class GitHubReviewEditRequest(GitHubReviewRequest):
    """Only the body of one immutable native submitted review can change."""

    object: GitHubObjectRef

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        """Keep review IDs distinct from issue-comment and review-comment IDs."""
        if (
            self.object.kind is not GitHubObjectKind.REVIEW
            or self.object.repository_id != self.target.repository_id
            or self.object.container_number != self.pr_scope.container_number
        ):
            raise ValueError(_MAINTENANCE_TARGET_INVALID)
        return self


class GitHubCommentMaintenanceOperation(StrEnum):
    """Finite native effects, separate from workflow acts."""

    EDIT = "edit"
    DELETE = "delete"


class GitHubCommentMaintenanceStage(StrEnum):
    """The stage whose evidence is reported; a read is never mutation acceptance."""

    ADMISSION = "admission"
    PREFLIGHT = "preflight"
    MUTATION = "mutation"
    ATTRIBUTION = "attribution"


class GitHubObjectMutation(BaseModel):
    """One confirmed native maintenance observation; neither current state nor complete history."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    object: GitHubObjectRef
    operation: GitHubCommentMaintenanceOperation
    session_id: str = Field(min_length=1)
    role: RoleName
    actor: GitHubAccount
    observed_at: AwareDatetime
    source: NativeGitHubPostSource = Field(default_factory=NativeGitHubPostSource)
    provider_status: int
    preflight_digest: str = Field(pattern=_DIGEST_PATTERN)
    body_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    edit_evidence: GitHubEditEvidence | None = None
    reviewed_sha: str | None = Field(default=None, pattern=_COMMIT_PATTERN)
    review_comment: GitHubReviewCommentPlacement | None = None

    @model_validator(mode="after")
    def validate_effect(self) -> Self:
        """Keep edit and deletion evidence distinct."""
        if (
            self.object.kind
            not in (GitHubObjectKind.ISSUE_COMMENT, GitHubObjectKind.REVIEW, GitHubObjectKind.REVIEW_COMMENT)
            or (
                self.object.kind is GitHubObjectKind.REVIEW
                and (self.operation is not GitHubCommentMaintenanceOperation.EDIT or self.reviewed_sha is None)
            )
            or (self.object.kind is not GitHubObjectKind.REVIEW and self.reviewed_sha is not None)
            or ((self.object.kind is GitHubObjectKind.REVIEW_COMMENT) != (self.review_comment is not None))
        ) or (
            (
                self.operation is GitHubCommentMaintenanceOperation.EDIT
                and (self.provider_status != 200 or self.body_digest is None)
            )
            or (
                self.operation is GitHubCommentMaintenanceOperation.DELETE
                and (self.provider_status != 204 or self.body_digest is not None)
            )
        ):
            raise ValueError(_MUTATION_EVIDENCE_INVALID)
        return self


class GitHubCommentMaintenanceResult(BaseModel):
    """Safe stage/acceptance facts plus separately confirmed durable mutation attribution."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    operation: GitHubCommentMaintenanceOperation
    object: GitHubObjectRef
    stage: GitHubCommentMaintenanceStage
    acceptance: GitHubAcceptance
    failure: GitHubPostFailure | None = None
    mutation: GitHubObjectMutation | None = None
    preflight_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    body_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    edit_evidence: GitHubEditEvidence | None = None
    reviewed_sha: str | None = None
    review_comment: GitHubReviewCommentPlacement | None = None
    provider_status: int | None = Field(default=None, ge=100, le=599)
    retry_after: timedelta | None = None
    credential_refusal: str | None = None

    @property
    def attributed(self) -> bool:
        """Require the maintenance append, independently of the existing creator record."""
        return (
            self.acceptance is GitHubAcceptance.CONFIRMED
            and self.failure is None
            and self.mutation is not None
            and self.mutation.object == self.object
            and self.mutation.operation is self.operation
        )


class GitHubPullRequestDescriptionOperation(StrEnum):
    """One additional finite native maintenance effect, without workflow authority."""

    EDIT = "edit_pr_description"


class GitHubPullRequestDescriptionMutation(BaseModel):
    """Later title/body attribution, never a replacement of the immutable PR creator."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    operation: Literal[GitHubPullRequestDescriptionOperation.EDIT] = GitHubPullRequestDescriptionOperation.EDIT
    object: GitHubObjectRef
    session_id: str
    role: RoleName
    actor: GitHubAccount
    observed_at: AwareDatetime
    head_sha: str = Field(pattern=_COMMIT_PATTERN)
    title_digest: str = Field(pattern=_DIGEST_PATTERN)
    body_digest: str = Field(pattern=_DIGEST_PATTERN)
    before_title_digest: str = Field(pattern=_DIGEST_PATTERN)
    before_body_digest: str = Field(pattern=_DIGEST_PATTERN)
    edit_evidence: GitHubEditEvidence
    source: NativeGitHubPostSource = Field(default_factory=NativeGitHubPostSource)
    provider_status: Literal[200] = 200

    @model_validator(mode="after")
    def require_pr(self) -> Self:
        """Never reinterpret a comment or sealed/reflected record as a PR description edit."""
        if self.object.kind is not GitHubObjectKind.PULL_REQUEST or self.role is not RoleName.BUILDER:
            raise ValueError(_MUTATION_EVIDENCE_INVALID)
        return self


GitHubObjectMutationRecord = GitHubObjectMutation | GitHubPullRequestDescriptionMutation
