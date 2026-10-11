"""Select one complete subscription inspection report after provider failover."""

from __future__ import annotations

import argparse
import hashlib
import sys
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from tools.release.attempt import ProviderAttempt, ProviderName, ProviderOutcome
from tools.release.report_models import LaneReport

_UTF8 = "utf-8"
_JSON_INDENT = 2
_CODEX = ProviderName.CODEX
_CLAUDE = ProviderName.CLAUDE
_ERROR = "No complete, valid, settled provider report is available."
_INPUT_INVALID = "A provider attempt or its report is unavailable or invalid."
_OUTPUT_EXISTS = "Inspector selection outputs must be new files."
_REPORT_HASH_MISMATCH = "A provider report does not match its recorded digest."


class SelectionFailure(StrEnum):
    """Typed reason that an otherwise available provider result was not selected."""

    ATTEMPT_FAILED = "attempt_failed"
    AUTH_UNSETTLED = "auth_unsettled"
    INCOMPLETE_REPORT = "incomplete_report"
    INVALID_REPORT = "invalid_report"
    PROVIDER_MISMATCH = "provider_mismatch"


class InspectorSelection(BaseModel):
    """One selected assessment with both provider outcomes retained for diagnosis."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    selected_provider: Literal["codex", "claude"]
    selected_report: LaneReport
    codex_attempt: ProviderAttempt
    claude_attempt: ProviderAttempt | None
    codex_selection_failure: SelectionFailure | None


class _ProviderResult(BaseModel):
    """A strict provider attempt paired with its optionally valid report."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    attempt: ProviderAttempt
    report: LaneReport | None


def _read_provider(attempt_path: Path, report_path: Path | None) -> _ProviderResult:
    """Load a typed attempt and validate report identity without judging its prose."""
    try:
        attempt = ProviderAttempt.model_validate_json(attempt_path.read_bytes())
    except (OSError, ValidationError):
        raise ValueError(_INPUT_INVALID) from None
    if report_path is None:
        return _ProviderResult(attempt=attempt, report=None)
    try:
        report = LaneReport.model_validate_json(report_path.read_bytes())
    except (OSError, ValidationError):
        return _ProviderResult(attempt=attempt, report=None)
    canonical = report.model_dump_json().encode(_UTF8)
    if attempt.report_sha256 != hashlib.sha256(canonical).hexdigest():
        return _ProviderResult(attempt=attempt, report=None)
    return _ProviderResult(attempt=attempt, report=report)


def _eligibility(result: _ProviderResult, provider: ProviderName) -> tuple[bool, SelectionFailure | None]:
    """Require success, a matching complete report, and durable provider state."""
    if result.attempt.provider is not provider:
        return False, SelectionFailure.PROVIDER_MISMATCH
    if result.attempt.outcome is not ProviderOutcome.SUCCEEDED or result.attempt.failure is not None:
        return False, SelectionFailure.ATTEMPT_FAILED
    if result.report is None:
        return False, SelectionFailure.INVALID_REPORT
    if not result.report.assessment_complete:
        return False, SelectionFailure.INCOMPLETE_REPORT
    if provider is ProviderName.CODEX and not result.attempt.auth_settled:
        return False, SelectionFailure.AUTH_UNSETTLED
    return True, None


def select_inspector_report(
    codex_attempt_path: Path,
    codex_report_path: Path | None,
    claude_attempt_path: Path | None,
    claude_report_path: Path | None,
) -> InspectorSelection:
    """Select Codex when fully settled; otherwise select the one Claude fallback."""
    codex = _read_provider(codex_attempt_path, codex_report_path)
    codex_ok, codex_failure = _eligibility(codex, _CODEX)
    if codex_ok and codex.report is not None:
        return InspectorSelection(
            selected_provider=_CODEX.value,
            selected_report=codex.report,
            codex_attempt=codex.attempt,
            claude_attempt=None,
            codex_selection_failure=None,
        )
    if claude_attempt_path is None:
        raise ValueError(_ERROR)
    claude = _read_provider(claude_attempt_path, claude_report_path)
    claude_ok, _claude_reason = _eligibility(claude, _CLAUDE)
    if claude_ok and claude.report is not None:
        return InspectorSelection(
            selected_provider=_CLAUDE.value,
            selected_report=claude.report,
            codex_attempt=codex.attempt,
            claude_attempt=claude.attempt,
            codex_selection_failure=codex_failure,
        )
    raise ValueError(_ERROR)


def main(argv: list[str] | None = None) -> int:
    """Write the selected report and a machine-readable provider-outcome record."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-attempt", type=Path, required=True)
    parser.add_argument("--codex-report", type=Path)
    parser.add_argument("--claude-attempt", type=Path)
    parser.add_argument("--claude-report", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="Write the selection and outcome record.")
    parser.add_argument("--report-output", type=Path, required=True, help="Write the selected validated report.")
    args = parser.parse_args(argv)
    if args.output == args.report_output or any(
        path.exists() or path.is_symlink() for path in (args.output, args.report_output)
    ):
        print(_OUTPUT_EXISTS, file=sys.stderr)
        return 1
    try:
        selection = select_inspector_report(
            args.codex_attempt,
            args.codex_report,
            args.claude_attempt,
            args.claude_report,
        )
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    args.output.write_text(selection.model_dump_json(indent=_JSON_INDENT) + "\n", encoding=_UTF8)
    args.report_output.write_text(selection.selected_report.model_dump_json(indent=_JSON_INDENT) + "\n", encoding=_UTF8)
    codex_state = "succeeded" if selection.codex_selection_failure is None else selection.codex_selection_failure.value
    print(f"Selected {selection.selected_provider}; Codex state: {codex_state}")
    if selection.claude_attempt is not None:
        claude_state = (
            "succeeded"
            if selection.claude_attempt.outcome is ProviderOutcome.SUCCEEDED
            else selection.claude_attempt.failure.value
            if selection.claude_attempt.failure is not None
            else _ERROR
        )
        print(f"Claude fallback: {claude_state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
