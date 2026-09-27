"""Dependency-free wire types for history search payloads."""

from __future__ import annotations

from typing import TypedDict


class HistorySearchRow(TypedDict):
    """Wire-safe history search row with both identity namespaces."""

    sort_timestamp: str
    timestamp: str
    computer: str
    agent: str
    project: str
    topic: str
    tc_id: str | None
    native_id: str | None


class HistorySearchPayload(TypedDict):
    """Search rows plus the count withheld by the worker default."""

    computer: str
    rows: list[HistorySearchRow]
    excluded_workers: int
