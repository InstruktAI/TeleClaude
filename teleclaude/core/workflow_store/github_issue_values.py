"""Values the GitHub sync reads from listed issues: their newest update, a stored timestamp, one issue by number."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from teleclaude.core.workflow_store.github_io_models import GitHubIssue

__all__ = ["issue_by_number", "latest_issue_timestamp", "parse_timestamp"]


def latest_issue_timestamp(issues: Sequence[GitHubIssue]) -> str | None:
    timestamps = [issue.updated_at for issue in issues if issue.updated_at is not None]
    return max(timestamps).isoformat() if timestamps else None


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def issue_by_number(issues: Sequence[GitHubIssue], number: int | None) -> GitHubIssue | None:
    return next((issue for issue in issues if issue.number == number), None) if number is not None else None
