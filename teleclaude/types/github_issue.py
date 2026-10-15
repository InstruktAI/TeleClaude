"""Verified GitHub assignment identity carried by session displays."""

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

GITHUB_ISSUE_FIELD = "github_issue"


class GitHubIssueReference(BaseModel):
    """One resolved issue and its independently bound work subject."""

    model_config = ConfigDict(frozen=True)

    number: int = Field(gt=0, strict=True)
    url: HttpUrl
    subject: str | None = None
