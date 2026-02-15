#!/usr/bin/env python3
"""Consensus arbiter for multi-lane release reports.

Consumes three AI lane reports (Claude, Codex, Gemini), resolves
classification conflicts via majority vote, and emits an authoritative
release decision as JSON.

Exit codes:
  0 — decision written successfully
  1 — fatal error (missing files, parse failures)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Literal, TypedDict


class ContractChange(TypedDict, total=False):
    surface: str
    item: str
    change_type: str
    details: str


class LaneReport(TypedDict):
    classification: str
    rationale: str
    contract_changes: list[ContractChange]
    release_notes: str


class ArbiterDecision(TypedDict):
    release_authorized: bool
    target_version: str
    authoritative_rationale: str
    lane_summary: dict[str, str | None]
    evidence: list[str]


Classification = Literal["patch", "minor", "none"]

VALID_CLASSIFICATIONS: set[str] = {"patch", "minor", "none"}

LANE_NAMES = ("claude", "codex", "gemini")


def load_report(path: Path) -> LaneReport | None:
    """Load and validate a single lane report. Returns None on failure."""
    if not path.exists():
        print(f"WARNING: {path} not found", file=sys.stderr)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARNING: {path} parse error: {exc}", file=sys.stderr)
        return None

    classification = data.get("classification")
    if classification not in VALID_CLASSIFICATIONS:
        print(f"WARNING: {path} invalid classification: {classification!r}", file=sys.stderr)
        return None

    return LaneReport(
        classification=data["classification"],
        rationale=data.get("rationale", ""),
        contract_changes=data.get("contract_changes", []),
        release_notes=data.get("release_notes", ""),
    )


def resolve_consensus(
    reports: dict[str, LaneReport | None],
) -> ArbiterDecision:
    """Apply consensus rules and return the arbiter decision payload."""
    lane_summary: dict[str, str | None] = {}
    valid_reports: dict[str, LaneReport] = {}
    evidence: list[str] = []

    for lane in LANE_NAMES:
        report = reports.get(lane)
        if report is not None:
            lane_summary[lane] = report["classification"]
            valid_reports[lane] = report
            evidence.append(f"{lane}-report.json")
        else:
            lane_summary[lane] = None

    # Fail-safe: all three reports required for consensus
    if len(valid_reports) < 3:
        return _decision(
            authorized=False,
            version="none",
            rationale=f"Only {len(valid_reports)}/3 valid reports — insufficient for consensus.",
            lane_summary=lane_summary,
            evidence=evidence,
        )

    # Count classifications
    classifications = [r["classification"] for r in valid_reports.values()]
    counts = Counter(classifications)
    most_common, most_count = counts.most_common(1)[0]

    # Majority consensus (2+ agree)
    if most_count >= 2:
        # Conservative override: majority says "none" but minority found contract changes.
        # Trust the minority — they detected real changes the majority missed.
        if most_common == "none":
            for lane, report in valid_reports.items():
                if report["classification"] != "none" and report["contract_changes"]:
                    minority_version = report["classification"]
                    return _decision(
                        authorized=True,
                        version=minority_version,
                        rationale=(
                            f"Majority says none but {lane} reports contract changes "
                            f"— overriding to {minority_version}."
                        ),
                        lane_summary=lane_summary,
                        evidence=evidence,
                    )

        authorized = most_common in ("patch", "minor")
        return _decision(
            authorized=authorized,
            version=most_common,
            rationale=f"{most_count}/3 lanes agree on {most_common}.",
            lane_summary=lane_summary,
            evidence=evidence,
        )

    # Three-way disagreement: compare contract_changes detail
    best_lane = _pick_most_detailed(valid_reports)
    if best_lane:
        chosen = valid_reports[best_lane]["classification"]
        authorized = chosen in ("patch", "minor")
        return _decision(
            authorized=authorized,
            version=chosen,
            rationale=f"Three-way split — {best_lane} has most detailed contract_changes, choosing {chosen}.",
            lane_summary=lane_summary,
            evidence=evidence,
        )

    # Fully ambiguous: conservative default
    return _decision(
        authorized=False,
        version="none",
        rationale="Three-way disagreement with no clear detail winner — defaulting to no release.",
        lane_summary=lane_summary,
        evidence=evidence,
    )


def _pick_most_detailed(reports: dict[str, LaneReport]) -> str | None:
    """Return the lane with the most contract_changes entries, or None if tied."""
    scored: list[tuple[str, int]] = []
    for lane, report in reports.items():
        changes = report["contract_changes"]
        scored.append((lane, len(changes)))

    scored.sort(key=lambda x: x[1], reverse=True)
    if len(scored) >= 2 and scored[0][1] > scored[1][1] and scored[0][1] > 0:
        return scored[0][0]
    return None


def _decision(
    *,
    authorized: bool,
    version: str,
    rationale: str,
    lane_summary: dict[str, str | None],
    evidence: list[str],
) -> ArbiterDecision:
    return ArbiterDecision(
        release_authorized=authorized,
        target_version=version,
        authoritative_rationale=rationale,
        lane_summary=lane_summary,
        evidence=evidence,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consensus arbiter for release reports")
    parser.add_argument("--claude-report", type=Path, default=Path("claude-report.json"))
    parser.add_argument("--codex-report", type=Path, default=Path("codex-report.json"))
    parser.add_argument("--gemini-report", type=Path, default=Path("gemini-report.json"))
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("arbiter-decision.json"),
        help="Output path for the decision JSON",
    )
    args = parser.parse_args(argv)

    reports: dict[str, LaneReport | None] = {
        "claude": load_report(args.claude_report),
        "codex": load_report(args.codex_report),
        "gemini": load_report(args.gemini_report),
    }

    decision = resolve_consensus(reports)
    args.output.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
