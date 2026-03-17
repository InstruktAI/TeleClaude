"""Characterization tests for the release consensus arbiter.

OBSERVE-ASSERT-VERIFY: These tests pin the observed behavior of
resolve_consensus() against the restored fixture scenarios.
"""

from __future__ import annotations

from pathlib import Path

from scripts.release_consolidator import LaneReport, load_report, resolve_consensus

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
