"""Characterization tests for the release consensus arbiter.

OBSERVE-ASSERT-VERIFY: These tests pin the observed behavior of
resolve_consensus() against the restored fixture scenarios.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typing_extensions import TypedDict

from scripts.release_consolidator import LaneReport, load_report, resolve_consensus

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "release-simulation"
SCENARIOS = FIXTURES / "scenarios"


class ExpectedScenario(TypedDict):
    release_authorized: bool
    target_version: str
    rationale_contains: str


def _load_scenario(name: str) -> dict[str, LaneReport | None]:
    """Load all three lane reports for a named scenario."""
    scenario_dir = SCENARIOS / name
    return {
        "claude": load_report(scenario_dir / "claude.json"),
        "codex": load_report(scenario_dir / "codex.json"),
        "gemini": load_report(scenario_dir / "gemini.json"),
    }


def _load_expected() -> dict[str, ExpectedScenario]:
    raw: dict[str, dict[str, object]] = json.loads(  # guard: loose-dict - JSON fixture data is untyped at parse time
        (FIXTURES / "expected.json").read_text()
    )
    result: dict[str, ExpectedScenario] = {}
    for k, v in raw.items():
        result[k] = ExpectedScenario(
            release_authorized=bool(v["release_authorized"]),
            target_version=str(v["target_version"]),
            rationale_contains=str(v["rationale_contains"]),
        )
    return result


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


class TestExpectedJsonAlignment:
    """Verify all scenarios match the expected.json fixture."""

    @pytest.mark.parametrize("scenario", ["unanimous", "split", "override"])
    def test_matches_expected(self, scenario: str) -> None:
        expected = _load_expected()[scenario]
        reports = _load_scenario(scenario)
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] == expected["release_authorized"]
        assert decision["target_version"] == expected["target_version"]
        rationale_fragment = str(expected["rationale_contains"])
        assert rationale_fragment in decision["authoritative_rationale"]


class TestEdgeCases:
    """Verify arbiter handles degenerate inputs."""

    def test_missing_report_blocks_release(self) -> None:
        reports: dict[str, LaneReport | None] = {
            "claude": _load_scenario("unanimous")["claude"],
            "codex": _load_scenario("unanimous")["codex"],
            "gemini": None,
        }
        decision = resolve_consensus(reports)
        assert decision["release_authorized"] is False
        assert "insufficient" in decision["authoritative_rationale"].lower()

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

    def test_decision_has_required_keys(self) -> None:
        reports = _load_scenario("unanimous")
        decision = resolve_consensus(reports)
        required: set[str] = {
            "release_authorized",
            "target_version",
            "authoritative_rationale",
            "lane_summary",
            "evidence",
        }
        assert required.issubset(decision.keys())
