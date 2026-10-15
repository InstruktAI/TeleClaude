"""Named procedure inputs that bind a session's work subject."""

from enum import StrEnum


class WorkSubjectParameter(StrEnum):
    """Structured assignment parameters recognized by session presentation."""

    ISSUE = "issue"
    BRANCH = "branch"
    SLUG = "slug"
