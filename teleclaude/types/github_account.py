"""Stable GitHub account facts shared by identity, storage and provider transport."""

from __future__ import annotations

from enum import StrEnum

from pydantic import ConfigDict, Field

from teleclaude.closed_model import ClosedModel


class GitHubAccountKind(StrEnum):
    """Provider account types carried by REST author/account facts."""

    USER = "User"
    BOT = "Bot"
    ORGANIZATION = "Organization"


class GitHubAccount(ClosedModel):
    """Stable provider identity; login is presentation and lookup input."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int = Field(gt=0, strict=True)
    node_id: str = Field(min_length=1)
    login: str = Field(min_length=1)
    type: GitHubAccountKind

    def same_account(self, other: GitHubAccount) -> bool:
        """Compare stable provider facts independently of login spelling."""
        return self.id == other.id and self.node_id == other.node_id and self.type is other.type
