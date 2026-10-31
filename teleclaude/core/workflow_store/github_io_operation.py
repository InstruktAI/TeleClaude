"""The closed set of provider operations the workflow store's GitHub I/O dispatches."""

from __future__ import annotations

from enum import StrEnum

__all__ = ["GitHubOperation"]


class GitHubOperation(StrEnum):
    """Closed set of provider operations used by sync and async callers."""

    OPEN_ISSUE = "open_issue"
    UPDATE_ISSUE = "update_issue"
    ENSURE_LABEL = "ensure_label"
    DELETE_LABEL = "delete_label"
    LIST_ISSUES = "list_issues"
    LIST_LABELS = "list_labels"
    GET_ISSUE = "get_issue"
    LIST_SUB_ISSUES = "list_sub_issues"
    ADD_SUB_ISSUE = "add_sub_issue"
    REMOVE_SUB_ISSUE = "remove_sub_issue"
    GET_PARENT = "get_parent"
    LIST_BLOCKED_BY = "list_blocked_by"
    ADD_BLOCKED_BY = "add_blocked_by"
    REMOVE_BLOCKED_BY = "remove_blocked_by"
    READ_COMMENTS = "read_comments"
    READ_COMMENT = "read_comment"
    READ_COMMENTS_AFTER = "read_comments_after"
    READ_COMMENTS_UPDATED_SINCE = "read_comments_updated_since"
    CREATE_COMMENT = "create_comment"
    UPDATE_COMMENT = "update_comment"
    LIST_ARTIFACTS = "list_artifacts"
    READ_ARTIFACT = "read_artifact"
    CREATE_ARTIFACT = "create_artifact"
    UPDATE_ARTIFACT = "update_artifact"
    DELETE_ARTIFACT = "delete_artifact"
