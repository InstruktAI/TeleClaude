#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Consensus arbiter for multi-lane release reports.

Consumes AI lane reports, resolves classification conflicts via majority
vote, and emits an authoritative release decision as JSON.

Enabled agents are read from config.yml (same resolution as `telec config get`).
Quorum scales dynamically: 1 agent → 1/1, 2 → 2/2, 3 → 2/3.
Arbiter preference for rationale: Claude > Codex > Gemini.

Exit codes:
  0 — valid decision written (release authorized or not)
  1 — quorum failure (fewer than required valid reports)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from operator import itemgetter
from pathlib import Path
from typing import Literal, TypedDict, cast

import yaml


class ContractChange(TypedDict, total=False):
    """A single API or contract change entry."""

    surface: str
    item: str
    change_type: str
    details: str


class LaneReport(TypedDict):
    """Parsed output from a single release-review lane."""

    classification: str
    rationale: str
    contract_changes: list[ContractChange]
    release_notes: str


class ArbiterDecision(TypedDict):
    """Final release decision emitted by the consensus arbiter."""

    release_authorized: bool
    quorum_met: bool
    target_version: str
    authoritative_rationale: str
    lane_summary: dict[str, str | None]
    evidence: list[str]


Classification = Literal["patch", "minor", "none"]

VALID_CLASSIFICATIONS: set[str] = {"patch", "minor", "none"}

# All known lane names in arbiter preference order (most trusted first).
ARBITER_PREFERENCE = ("claude", "codex", "gemini")


def runtime_config_path() -> Path | None:
    """Host runtime config location, independent of the caller's cwd.

    Resolves from ``$TELECLAUDE_HOME`` — the platform's runtime-home authority,
    the same env ``teleclaude.paths`` reads — so the arbiter sees the host's
    installed config, never a file that happens to sit in the working directory.
    Returns ``None`` when the env is unset: a portable script must not hardcode
    ``~/.teleclaude`` (that default belongs to ``teleclaude.paths``).
    """
    home = os.environ.get("TELECLAUDE_HOME")
    return Path(home) / "config.yml" if home else None


def get_enabled_agents(config_path: Path | None = None) -> list[str]:
    """Read enabled agents from config.yml in arbiter preference order."""
    if config_path is None:
        config_path = runtime_config_path()
    if config_path is None or not config_path.exists():
        where = config_path or "$TELECLAUDE_HOME unset and no --config"
        print(f"WARNING: config not found ({where}), defaulting to all agents", file=sys.stderr)
        return list(ARBITER_PREFERENCE)

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    agents_raw = raw.get("agents", {})
    if not isinstance(agents_raw, dict):
        print("WARNING: agents section invalid, defaulting to all agents", file=sys.stderr)
        return list(ARBITER_PREFERENCE)

    enabled = []
    for name in ARBITER_PREFERENCE:
        agent_cfg = agents_raw.get(name)
        if isinstance(agent_cfg, dict) and agent_cfg.get("enabled", True):
            enabled.append(name)
        elif agent_cfg is None:
            # Agent not mentioned in config — skip
            pass

    if not enabled:
        print("WARNING: no enabled agents found, defaulting to all agents", file=sys.stderr)
        return list(ARBITER_PREFERENCE)

    return enabled


def _required_quorum(n_enabled: int) -> int:
    """Dynamic quorum: 1→1, 2→2, 3→2."""
    if n_enabled <= 2:
        return n_enabled
    return n_enabled - 1


def load_report(path: Path) -> LaneReport | None:
    """Load and validate a single lane report. Returns None on failure."""
    if not path.exists():
        print(f"WARNING: {path} not found", file=sys.stderr)
        return None
    try:
        loaded_data: object = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARNING: {path} parse error: {exc}", file=sys.stderr)
        return None
    data_obj = loaded_data

    if not isinstance(data_obj, dict):
        print(f"WARNING: {path} payload is not an object", file=sys.stderr)
        return None

    data = cast(dict[str, object], data_obj)  # guard: loose-dict - JSON parsed data — release report

    classification = data.get("classification")
    if not isinstance(classification, str) or classification not in VALID_CLASSIFICATIONS:
        print(f"WARNING: {path} invalid classification: {classification!r}", file=sys.stderr)
        return None

    rationale = data.get("rationale", "")
    contract_changes = data.get("contract_changes", [])
    release_notes = data.get("release_notes", "")
    if not isinstance(rationale, str) or not isinstance(contract_changes, list) or not isinstance(release_notes, str):
        print(f"WARNING: {path} has invalid field types", file=sys.stderr)
        return None

    return LaneReport(
        classification=classification,
        rationale=rationale,
        contract_changes=[cast(ContractChange, item) for item in contract_changes if isinstance(item, dict)],
        release_notes=release_notes,
    )


def resolve_consensus(
    reports: dict[str, LaneReport | None],
    enabled_agents: list[str],
) -> ArbiterDecision:
    """Apply consensus rules and return the arbiter decision payload."""
    lane_summary: dict[str, str | None] = {}
    valid_reports: dict[str, LaneReport] = {}
    evidence: list[str] = []

    for lane in enabled_agents:
        report = reports.get(lane)
        if report is not None:
            lane_summary[lane] = report["classification"]
            valid_reports[lane] = report
            evidence.append(f"{lane}-report.json")
        else:
            lane_summary[lane] = None

    n_enabled = len(enabled_agents)
    n_valid = len(valid_reports)
    quorum = _required_quorum(n_enabled)

    if n_valid < quorum:
        return _decision(
            authorized=False,
            quorum_met=False,
            version="none",
            rationale=f"Only {n_valid}/{n_enabled} valid reports — need at least {quorum} for quorum.",
            lane_summary=lane_summary,
            evidence=evidence,
        )

    # Count classifications
    classifications = [r["classification"] for r in valid_reports.values()]
    counts = Counter(classifications)
    most_common, most_count = counts.most_common(1)[0]

    # Majority consensus (2+ agree, or unanimous for 1-agent)
    if most_count >= quorum:
        # Conservative override: majority says "none" but minority found contract changes.
        # Trust the minority — they detected real changes the majority missed.
        if most_common == "none":
            for lane, report in valid_reports.items():
                if report["classification"] != "none" and report["contract_changes"]:
                    minority_version = report["classification"]
                    return _decision(
                        authorized=True,
                        quorum_met=True,
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
            quorum_met=True,
            version=most_common,
            rationale=f"{most_count}/{n_valid} lanes agree on {most_common}.",
            lane_summary=lane_summary,
            evidence=evidence,
        )

    # Disagreement — pick by arbiter preference order (Claude > Codex > Gemini)
    arbiter_lane = _pick_arbiter(valid_reports, enabled_agents)
    if arbiter_lane:
        chosen = valid_reports[arbiter_lane]["classification"]
        authorized = chosen in ("patch", "minor")
        return _decision(
            authorized=authorized,
            quorum_met=True,
            version=chosen,
            rationale=f"Disagreement — {arbiter_lane} (arbiter preference) decides: {chosen}.",
            lane_summary=lane_summary,
            evidence=evidence,
        )

    # Fully ambiguous: conservative default
    return _decision(
        authorized=False,
        quorum_met=True,
        version="none",
        rationale="Disagreement with no arbiter available — defaulting to no release.",
        lane_summary=lane_summary,
        evidence=evidence,
    )


def _pick_arbiter(reports: dict[str, LaneReport], enabled_agents: list[str]) -> str | None:
    """Pick the arbiter by preference order. Falls back to most-detailed if preferred has no detail."""
    enabled_set = set(enabled_agents)

    # First: prefer by arbiter order if the report has contract_changes
    for lane in ARBITER_PREFERENCE:
        if lane in enabled_set and lane in reports and reports[lane]["contract_changes"]:
            return lane

    # Fallback: most detailed report by contract_changes count
    scored: list[tuple[str, int]] = []
    for lane, report in reports.items():
        scored.append((lane, len(report["contract_changes"])))

    scored.sort(key=itemgetter(1), reverse=True)
    if len(scored) >= 2 and scored[0][1] > scored[1][1] and scored[0][1] > 0:
        return scored[0][0]

    # Last resort: first enabled agent in arbiter preference order
    for lane in ARBITER_PREFERENCE:
        if lane in enabled_set and lane in reports:
            return lane
    return None


def _decision(
    *,
    authorized: bool,
    quorum_met: bool,
    version: str,
    rationale: str,
    lane_summary: dict[str, str | None],
    evidence: list[str],
) -> ArbiterDecision:
    return ArbiterDecision(
        release_authorized=authorized,
        quorum_met=quorum_met,
        target_version=version,
        authoritative_rationale=rationale,
        lane_summary=lane_summary,
        evidence=evidence,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: load lane reports, run consensus, write decision JSON."""
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
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Explicit config.yml path (default: $TELECLAUDE_HOME/config.yml)",
    )
    args = parser.parse_args(argv)

    enabled_agents = get_enabled_agents(args.config)
    print(f"Enabled agents: {', '.join(enabled_agents)}", file=sys.stderr)
    print(f"Quorum required: {_required_quorum(len(enabled_agents))}/{len(enabled_agents)}", file=sys.stderr)

    report_paths: dict[str, Path] = {
        "claude": args.claude_report,
        "codex": args.codex_report,
        "gemini": args.gemini_report,
    }
    reports: dict[str, LaneReport | None] = {
        name: load_report(path) if name in enabled_agents else None for name, path in report_paths.items()
    }

    decision = resolve_consensus(reports, enabled_agents)
    args.output.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, indent=2))

    if not decision["quorum_met"]:
        print("FATAL: quorum not met — aborting", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
