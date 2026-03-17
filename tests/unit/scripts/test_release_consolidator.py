"""Characterization tests for the release consensus arbiter.

OBSERVE-ASSERT-VERIFY: These tests pin the observed behavior of
resolve_consensus() against the restored fixture scenarios.
"""

from __future__ import annotations

from pathlib import Path

from scripts.release_consolidator import LaneReport, load_report, main, resolve_consensus

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "release-simulation"
SCENARIOS = FIXTURES / "scenarios"


def _load_scenario(name: str) -> dict[str, LaneReport | None]:
    """Load all three lane reports for a named scenario."""
    scenario_dir = SCENARIOS / name
    return {
        "claude": load_report(scenario_dir / "claude.json"),
        "codex": load_report(scenario_dir / "codex.json"),
        "gemini": load_report(scenario_dir / "gemini.json"),
    }


class TestUnanimousScenario:
    """All three lanes agree on 'patch'."""

    def test_release_authorized(self) -> None:
        reports = _load_scenario("unanimous")
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is True

    def test_target_version(self) -> None:
        reports = _load_scenario("unanimous")
        decision = resolve_consensus(reports)
        assert decision["target_version"] == "patch"

    def test_rationale_mentions_consensus(self) -> None:
        reports = _load_scenario("unanimous")
        decision = resolve_consensus(reports)
        assert "3/3 lanes agree" in decision["authoritative_rationale"]

    def test_lane_summary_all_patch(self) -> None:
        reports = _load_scenario("unanimous")
        decision = resolve_consensus(reports)
        for lane in ("claude", "codex", "gemini"):
            assert decision["lane_summary"][lane] == "patch"


class TestSplitScenario:
    """Two lanes say 'patch', one says 'minor' — majority wins."""

    def test_release_authorized(self) -> None:
        reports = _load_scenario("split")
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is True

    def test_target_version(self) -> None:
        reports = _load_scenario("split")
        decision = resolve_consensus(reports)
        assert decision["target_version"] == "patch"

    def test_rationale_mentions_majority(self) -> None:
        reports = _load_scenario("split")
        decision = resolve_consensus(reports)
        assert "2/3 lanes agree" in decision["authoritative_rationale"]


class TestOverrideScenario:
    """Two lanes say 'none' but one reports contract changes — override."""

    def test_release_authorized(self) -> None:
        reports = _load_scenario("override")
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is True

    def test_target_version(self) -> None:
        reports = _load_scenario("override")
        decision = resolve_consensus(reports)
        assert decision["target_version"] == "patch"

    def test_rationale_mentions_contract_changes(self) -> None:
        reports = _load_scenario("override")
        decision = resolve_consensus(reports)
        assert "contract changes" in decision["authoritative_rationale"]


class TestEdgeCases:
    """Verify arbiter handles degenerate inputs."""

    def test_missing_report_meets_quorum_with_two(self) -> None:
        """Two agreeing reports with one missing still meets quorum."""
        reports: dict[str, LaneReport | None] = {
            "claude": _load_scenario("unanimous")["claude"],
            "codex": _load_scenario("unanimous")["codex"],
            "gemini": None,
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is True
        assert "2/" in decision["authoritative_rationale"]

    def test_single_report_blocks_release(self) -> None:
        """Only one report is below quorum — release blocked."""
        reports: dict[str, LaneReport | None] = {
            "claude": _load_scenario("unanimous")["claude"],
            "codex": None,
            "gemini": None,
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is False
        assert "quorum" in decision["authoritative_rationale"].lower()

    def test_all_none_classification(self) -> None:
        none_report: LaneReport = {
            "classification": "none",
            "rationale": "No changes",
            "contract_changes": [],
            "release_notes": "",
        }
        reports: dict[str, LaneReport | None] = {
            "claude": none_report,
            "codex": none_report,
            "gemini": none_report,
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is False
        assert decision["target_version"] == "none"


class TestQuorumMetField:
    """Verify quorum_met is set correctly in all decision paths."""

    def test_quorum_failure_sets_quorum_met_false(self) -> None:
        """Only one report → quorum_met=False."""
        reports: dict[str, LaneReport | None] = {
            "claude": _load_scenario("unanimous")["claude"],
            "codex": None,
            "gemini": None,
        }
        decision = resolve_consensus(reports)
        assert decision["quorum_met"] is False

    def test_unanimous_none_sets_quorum_met_true(self) -> None:
        """All lanes say 'none' → quorum_met=True, release_authorized=False."""
        none_report: LaneReport = {
            "classification": "none",
            "rationale": "No changes",
            "contract_changes": [],
            "release_notes": "",
        }
        reports: dict[str, LaneReport | None] = {
            "claude": none_report,
            "codex": none_report,
            "gemini": none_report,
        }
        decision = resolve_consensus(reports)
        assert decision["quorum_met"] is True
        assert decision["release_authorized"] is False

    def test_authorized_release_sets_quorum_met_true(self) -> None:
        """Unanimous patch → quorum_met=True, release_authorized=True."""
        reports = _load_scenario("unanimous")
        decision = resolve_consensus(reports)
        assert decision["quorum_met"] is True
        assert decision["release_authorized"] is True

    def test_zero_reports_sets_quorum_met_false(self) -> None:
        """No reports at all → quorum_met=False."""
        reports: dict[str, LaneReport | None] = {
            "claude": None,
            "codex": None,
            "gemini": None,
        }
        decision = resolve_consensus(reports)
        assert decision["quorum_met"] is False


class TestMainExitCodes:
    """Verify main() exit codes match quorum state."""

    def test_main_returns_1_on_quorum_failure(self, tmp_path: Path) -> None:
        """Quorum not met → exit 1."""
        # Write only one valid report
        import json

        report = {"classification": "patch", "rationale": "test", "contract_changes": [], "release_notes": ""}
        (tmp_path / "claude-report.json").write_text(json.dumps(report))
        # Missing codex and gemini → quorum fails
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
        assert exit_code == 1

    def test_main_returns_0_on_valid_no_release(self, tmp_path: Path) -> None:
        """Quorum met, unanimous 'none' → exit 0."""
        import json

        none_report = {"classification": "none", "rationale": "nothing", "contract_changes": [], "release_notes": ""}
        for name in ("claude", "codex", "gemini"):
            (tmp_path / f"{name}-report.json").write_text(json.dumps(none_report))
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

    def test_main_returns_0_on_authorized_release(self, tmp_path: Path) -> None:
        """Quorum met, release authorized → exit 0."""
        import json

        patch_report = {
            "classification": "patch",
            "rationale": "bugfix",
            "contract_changes": [],
            "release_notes": "fix",
        }
        for name in ("claude", "codex", "gemini"):
            (tmp_path / f"{name}-report.json").write_text(json.dumps(patch_report))
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
