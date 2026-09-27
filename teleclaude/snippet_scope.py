"""Lightweight owner for snippet publication scopes."""

from __future__ import annotations

from enum import StrEnum


class SnippetScope(StrEnum):
    """Closed scope values materialized in the snippet index."""

    GLOBAL = "global"
    PROJECT = "project"
    PERSON = "person"
    COMPANY = "company"
