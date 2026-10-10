"""Typed completion values returned by operation work owners."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OperationCompletion:
    """Carry unchanged operation result text beside an optional owner declaration."""

    result: str
    work_feedback: str | None = None
