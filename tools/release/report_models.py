"""Typed loader for the shared AI release-report contract."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tools.release.attempt import ReleaseDecisionMode

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


class ManualSummaryReport(BaseModel):
    """Optional notes for an already selected version, without an assessment."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    release_notes: str = Field(min_length=1)
    summary_complete: bool


InspectorReport = LaneReport | ManualSummaryReport


def report_model(mode: ReleaseDecisionMode) -> type[LaneReport] | type[ManualSummaryReport]:
    """Choose the schema from the frozen decision, never from provider output."""
    if mode is ReleaseDecisionMode.MANUAL:
        return ManualSummaryReport
    return LaneReport


def report_complete(report: InspectorReport) -> bool:
    """Read the completion field owned by the explicit report type."""
    if isinstance(report, ManualSummaryReport):
        return report.summary_complete
    return report.assessment_complete


def load_report(path: Path) -> LaneReport:
    """Read and strictly validate one report against the shared schema model."""
    return LaneReport.model_validate_json(path.read_text(encoding=_UTF8_ENCODING))
