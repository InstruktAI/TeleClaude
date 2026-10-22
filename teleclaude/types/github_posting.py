"""Posting-source, provider acceptance and immutable attribution facts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from teleclaude.core.roles import RoleName
from teleclaude.types.github_account import GitHubAccount

_SOURCE_DISCRIMINATOR = "kind"
_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_MIRROR_ORDER_INVALID = "Mirror part must be within its source-owned total"
_REVIEW_HEAD_REQUIRED = "A review association requires the exact reviewed SHA"


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

    @model_validator(mode="after")
    def require_review_head(self) -> Self:
        """Keep a review's actual head separate from its prose and source identity."""
        if self.object.kind is GitHubObjectKind.REVIEW and self.reviewed_sha is None:
            raise ValueError(_REVIEW_HEAD_REQUIRED)
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

    @property
    def attributed(self) -> bool:
        """Report completion from the posting owner's recorded-association result."""
        return (
            self.acceptance is GitHubAcceptance.CONFIRMED
            and self.failure is None
            and self.association is not None
            and self.object == self.association.object
        )
