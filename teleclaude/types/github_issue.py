"""Local GitHub assignment links carried by session displays."""

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_serializer

GITHUB_ISSUE_FIELD = "github_issue"
_URL_FIELD = "url"


class GitHubIssueReference(BaseModel):
    """One assigned issue address and its recorded work subject, without a provider-state claim."""

    model_config = ConfigDict(frozen=True)

    number: int = Field(gt=0, strict=True)
    url: HttpUrl
    subject: str | None = None

    @field_serializer(_URL_FIELD)
    def serialize_url(self, url: HttpUrl) -> str:
        """Keep issue references JSON-safe in every enclosing DTO dump mode."""
        return str(url)
