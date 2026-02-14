"""Tests for the release consensus arbiter."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.release_consolidator import (
    LaneReport,
    _pick_most_detailed,
    load_report,
    resolve_consensus,
)


def _report(classification: str, contract_changes: int = 0) -> LaneReport:
    """Build a minimal lane report for testing."""
    changes = [
        {"surface": "cli", "item": f"cmd-{i}", "change_type": "added", "details": f"test change {i}"}
        for i in range(contract_changes)
    ]
    return LaneReport(
        classification=classification,
        rationale=f"Test rationale for {classification}",
        contract_changes=changes,
        release_notes=f"Test notes for {classification}",
    )


def _write_report(path: Path, report: LaneReport) -> None:
    path.write_text(json.dumps(report), encoding="utf-8")


# --- load_report ---


class TestLoadReport:
    def test_valid_report(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report.json"
        _write_report(report_path, _report("minor", 1))
        result = load_report(report_path)
        assert result is not None
        assert result["classification"] == "minor"

    def test_missing_file(self, tmp_path: Path) -> None:
        result = load_report(tmp_path / "nonexistent.json")
        assert result is None

    def test_invalid_json(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report.json"
        report_path.write_text("not json", encoding="utf-8")
        result = load_report(report_path)
        assert result is None

    def test_invalid_classification(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps({"classification": "major"}), encoding="utf-8")
        result = load_report(report_path)
        assert result is None


# --- resolve_consensus ---


class TestMajorityConsensus:
    def test_two_minor_one_patch(self) -> None:
        reports = {
            "claude": _report("minor"),
            "codex": _report("minor"),
            "gemini": _report("patch"),
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is True
        assert decision["target_version"] == "minor"
        assert decision["needs_human"] is False
        assert "2/3" in decision["authoritative_rationale"]

    def test_two_patch_one_minor(self) -> None:
        reports = {
            "claude": _report("patch"),
            "codex": _report("minor"),
            "gemini": _report("patch"),
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is True
        assert decision["target_version"] == "patch"

    def test_unanimous_none(self) -> None:
        reports = {
            "claude": _report("none"),
            "codex": _report("none"),
            "gemini": _report("none"),
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is False
        assert decision["target_version"] == "none"
        assert decision["needs_human"] is False

    def test_two_none_one_patch_no_changes(self) -> None:
        reports = {
            "claude": _report("none"),
            "codex": _report("none"),
            "gemini": _report("patch", contract_changes=0),
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is False
        assert decision["target_version"] == "none"
        assert decision["needs_human"] is False


class TestConservativeOverride:
    def test_majority_none_minority_has_changes(self) -> None:
        reports = {
            "claude": _report("none"),
            "codex": _report("none"),
            "gemini": _report("minor", contract_changes=2),
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is False
        assert decision["needs_human"] is True
        assert "contract changes" in decision["authoritative_rationale"]

    def test_majority_none_patch_minority_with_changes(self) -> None:
        reports = {
            "claude": _report("none"),
            "codex": _report("none"),
            "gemini": _report("patch", contract_changes=1),
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is False
        assert decision["needs_human"] is True
        assert "contract changes" in decision["authoritative_rationale"]


class TestFailSafe:
    def test_one_valid_report(self) -> None:
        reports: dict[str, LaneReport | None] = {
            "claude": _report("minor"),
            "codex": None,
            "gemini": None,
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is False
        assert decision["needs_human"] is True
        assert "insufficient" in decision["authoritative_rationale"].lower()

    def test_two_agreeing_reports_one_none(self) -> None:
        reports: dict[str, LaneReport | None] = {
            "claude": _report("patch"),
            "codex": _report("patch"),
            "gemini": None,
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is False
        assert decision["needs_human"] is True
        assert "insufficient" in decision["authoritative_rationale"].lower()

    def test_two_disagreeing_reports_one_none(self) -> None:
        reports: dict[str, LaneReport | None] = {
            "claude": _report("minor"),
            "codex": _report("patch"),
            "gemini": None,
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is False
        assert decision["needs_human"] is True
        assert "insufficient" in decision["authoritative_rationale"].lower()

    def test_zero_valid_reports(self) -> None:
        reports: dict[str, LaneReport | None] = {
            "claude": None,
            "codex": None,
            "gemini": None,
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is False
        assert decision["needs_human"] is True


class TestThreeWayDisagreement:
    def test_all_different_with_detail_winner(self) -> None:
        reports = {
            "claude": _report("minor", contract_changes=3),
            "codex": _report("patch", contract_changes=1),
            "gemini": _report("none", contract_changes=0),
        }
        decision = resolve_consensus(reports)
        assert decision["needs_human"] is True
        assert decision["target_version"] == "minor"
        assert decision["release_authorized"] is True

    def test_all_different_no_detail_winner(self) -> None:
        reports = {
            "claude": _report("minor", contract_changes=0),
            "codex": _report("patch", contract_changes=0),
            "gemini": _report("none", contract_changes=0),
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is False
        assert decision["needs_human"] is True
        assert decision["target_version"] == "none"


class TestPickMostDetailed:
    def test_tied_nonzero_counts_returns_none(self) -> None:
        reports = {
            "claude": _report("minor", contract_changes=2),
            "codex": _report("patch", contract_changes=2),
            "gemini": _report("none", contract_changes=2),
        }
        assert _pick_most_detailed(reports) is None


class TestLaneSummaryAndEvidence:
    def test_lane_summary_populated(self) -> None:
        reports = {
            "claude": _report("minor"),
            "codex": _report("minor"),
            "gemini": _report("minor"),
        }
        decision = resolve_consensus(reports)
        assert decision["lane_summary"] == {
            "claude": "minor",
            "codex": "minor",
            "gemini": "minor",
        }

    def test_evidence_includes_valid_reports(self) -> None:
        reports: dict[str, LaneReport | None] = {
            "claude": _report("patch"),
            "codex": None,
            "gemini": _report("patch"),
        }
        decision = resolve_consensus(reports)
        assert "claude-report.json" in decision["evidence"]
        assert "gemini-report.json" in decision["evidence"]
        assert "codex-report.json" not in decision["evidence"]

    def test_missing_lane_shows_none(self) -> None:
        reports: dict[str, LaneReport | None] = {
            "claude": _report("patch"),
            "codex": None,
            "gemini": _report("patch"),
        }
        decision = resolve_consensus(reports)
        assert decision["lane_summary"]["codex"] is None


# --- main CLI integration ---


class TestMainCLI:
    def test_main_writes_decision(self, tmp_path: Path) -> None:
        from scripts.release_consolidator import main

        for lane in ("claude", "codex", "gemini"):
            _write_report(tmp_path / f"{lane}-report.json", _report("patch"))

        exit_code = main(
            [
                "--claude-report",
                str(tmp_path / "claude-report.json"),
                "--codex-report",
                str(tmp_path / "codex-report.json"),
                "--gemini-report",
                str(tmp_path / "gemini-report.json"),
                "-o",
                str(tmp_path / "decision.json"),
            ]
        )
        assert exit_code == 0
        decision = json.loads((tmp_path / "decision.json").read_text(encoding="utf-8"))
        assert decision["release_authorized"] is True

    def test_main_returns_2_when_needs_human(self, tmp_path: Path) -> None:
        from scripts.release_consolidator import main

        _write_report(tmp_path / "claude-report.json", _report("minor"))
        # Only one report — fail-safe triggers

        exit_code = main(
            [
                "--claude-report",
                str(tmp_path / "claude-report.json"),
                "--codex-report",
                str(tmp_path / "nonexistent.json"),
                "--gemini-report",
                str(tmp_path / "nonexistent.json"),
                "-o",
                str(tmp_path / "decision.json"),
            ]
        )
        assert exit_code == 2
