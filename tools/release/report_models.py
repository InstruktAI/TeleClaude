"""Typed loader for the shared AI release-report contract."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

_UTF8_ENCODING = "utf-8"


class ContractChange(BaseModel):
    """One declared public-surface change in a lane report."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    surface: Literal["cli", "events", "config"]
    item: str
    change_type: Literal["added", "modified", "removed"]
    details: str


class LaneReport(BaseModel):
    """A report matching the project's release-report schema."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    classification: Literal["patch", "minor", "none"]
    rationale: str
    contract_changes: list[ContractChange]
    release_notes: str
    assessment_complete: bool


def load_report(path: Path) -> LaneReport:
    """Read and strictly validate one report against the shared schema model."""
    return LaneReport.model_validate_json(path.read_text(encoding=_UTF8_ENCODING))
