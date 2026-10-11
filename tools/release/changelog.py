#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Generate changelog sections from git commits or one selected inspection report.

Produces Keep a Changelog formatted sections for GitHub releases
and CHANGELOG.md maintenance.

Usage:
  # From the selected inspection report (release path)
  uv run python -m tools.release.changelog from-report \\
    --tag v0.6.0 --since v0.5.0 \\
    --report selected-report.json \\
    --output release-notes.md --prepend CHANGELOG.md

  # From git log only (backfill / fallback)
  uv run python -m tools.release.changelog from-git \\
    --tag v0.5.0 --since v0.4.0 \\
    --output release-notes.md

Exit codes:
  0 — section generated
  1 — fatal error
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

# Anchor git operations to this script's own repository, so commit history is
# read from the repo the tool ships in regardless of the caller's cwd (the
# script-location resolution the standalone-execution policy mandates).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.release.report_models import load_report  # noqa: E402 -- resolve sibling release modules from any cwd

# ---------------------------------------------------------------------------
# Commit parsing
# ---------------------------------------------------------------------------

COMMITIZEN_RE = re.compile(r"^(\w+)(?:\(([^)]+)\))?: (.+)")

# Commitizen type → Keep a Changelog category
TYPE_CATEGORY: dict[str, str] = {
    "feat": "Added",
    "fix": "Fixed",
    "refactor": "Changed",
    "perf": "Changed",
    "revert": "Changed",
}

# Noise patterns: commits matching any of these are filtered out
NOISE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p)
    for p in [
        r"\[skip ci\]",
        r"\[ci skip\]",
        r"^chore\(todos?\):",
        r"^chore: bump version",
        r"^chore: sync",
        r"^chore\([^)]+\): todo cleanup",
        r"^chore\([^)]+\): delivery bookkeeping",
        r"^chore\([^)]+\): scaffold",
        r"^chore\([^)]+\): dump\b",
        r"^chore\([^)]+\): remove\b",
        r"^chore\(roadmap\):",
        r"^chore\(generated-",
        r"^Merge ",
    ]
]


def parse_commitizen(msg: str) -> tuple[str, str, str] | None:
    """Parse 'type(scope): subject'. Returns (type, scope, subject) or None."""
    m = COMMITIZEN_RE.match(msg)
    if m:
        return m.group(1), m.group(2) or "", m.group(3)
    return None


def is_noise(msg: str) -> bool:
    """True if the commit message matches a noise pattern."""
    return any(p.search(msg) for p in NOISE_PATTERNS)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def git_log_subjects(since: str, until: str = "HEAD") -> list[str]:
    """Return commit subjects between two refs (newest first)."""
    result = subprocess.run(
        ["git", "log", "--format=%s", f"{since}..{until}"],
        capture_output=True,
        text=True,
        check=True,
        cwd=_REPO_ROOT,
    )
    return [line for line in result.stdout.strip().split("\n") if line.strip()]


def git_tag_date(tag: str) -> str:
    """Return the date (YYYY-MM-DD) of a tag."""
    result = subprocess.run(
        ["git", "tag", "-l", "--format=%(creatordate:short)", tag],
        capture_output=True,
        text=True,
        check=True,
        cwd=_REPO_ROOT,
    )
    date = result.stdout.strip()
    if not date:
        date = datetime.now(UTC).strftime("%Y-%m-%d")
    return date


# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------


def categorize_commits(subjects: list[str]) -> dict[str, list[str]]:
    """Sort commit subjects into Keep a Changelog categories."""
    cats: dict[str, list[str]] = defaultdict(list)

    for msg in subjects:
        if is_noise(msg):
            continue

        parsed = parse_commitizen(msg)
        if parsed is None:
            # Non-commitizen — include as Changed if not a merge
            if not msg.startswith("Merge "):
                cats["Changed"].append(msg)
            continue

        ctype, scope, subject = parsed
        category = TYPE_CATEGORY.get(ctype)
        if category is None:
            continue  # skip chore, docs, test, style, ci, etc.

        entry = f"**{scope}:** {subject}" if scope else subject
        cats[category].append(entry)

    return dict(cats)


# ---------------------------------------------------------------------------
# Selected report formatting
# ---------------------------------------------------------------------------

CHANGE_TYPE_CATEGORY: dict[str, str] = {
    "added": "Added",
    "modified": "Changed",
    "removed": "Removed",
}


def categorize_report(report_path: Path) -> tuple[str, dict[str, list[str]]]:
    """Format only one complete report already selected by the inspector boundary."""
    report = load_report(report_path)
    if not report.assessment_complete:
        raise ValueError("The selected inspection report is incomplete.")
    cats: dict[str, list[str]] = defaultdict(list)
    for change in report.contract_changes:
        category = CHANGE_TYPE_CATEGORY[change.change_type]
        entry = f"**{change.surface.upper()}:** `{change.item}` — {change.details}"
        cats[category].append(entry)
    return report.release_notes, dict(cats)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

SECTION_ORDER = ("Added", "Changed", "Fixed", "Removed")


def format_section(
    version: str,
    date: str,
    categories: dict[str, list[str]],
    highlights: str = "",
    compare_base: str = "",
    repo_url: str = "",
) -> str:
    """Format a Keep a Changelog section."""
    lines: list[str] = [f"## [{version}] - {date}"]

    if highlights:
        lines.append("")
        lines.append(highlights.strip())

    for cat in SECTION_ORDER:
        entries = categories.get(cat, [])
        if not entries:
            continue
        lines.append("")
        lines.append(f"### {cat}")
        lines.append("")
        for entry in entries:
            lines.append(f"- {entry}")

    if compare_base and repo_url:
        lines.append("")
        lines.append(f"**Full diff:** [{compare_base}...v{version}]({repo_url}/compare/{compare_base}...v{version})")

    return "\n".join(lines)


def prepend_to_changelog(section: str, path: Path) -> None:
    """Prepend a version section to CHANGELOG.md (after the header)."""
    if path.exists():
        content = path.read_text(encoding="utf-8")
    else:
        content = (
            "# Changelog\n\n"
            "All notable changes to TeleClaude are documented in this file.\n\n"
            "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).\n"
        )

    lines = content.split("\n")
    # Find the first version heading to insert before it
    insert_at = len(lines)
    for i, line in enumerate(lines):
        if line.startswith("## ["):
            insert_at = i
            break

    new_lines = lines[:insert_at] + [section, ""] + lines[insert_at:]
    path.write_text("\n".join(new_lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_from_git(args: argparse.Namespace) -> int:
    """Generate changelog from git log."""
    version = args.tag.lstrip("v")
    date = args.date or git_tag_date(args.tag)

    subjects = git_log_subjects(args.since, args.until or args.tag)
    categories = categorize_commits(subjects)

    if not any(categories.values()):
        print(f"No notable changes between {args.since} and {args.tag}", file=sys.stderr)
        return 0

    section = format_section(
        version=version,
        date=date,
        categories=categories,
        compare_base=args.since,
        repo_url=args.repo_url,
    )

    _output(section, args)
    return 0


def cmd_from_report(args: argparse.Namespace) -> int:
    """Generate changelog from the one validated selected report + git log."""
    version = args.tag.lstrip("v")
    date = args.date or git_tag_date(args.tag)

    highlights, contract_cats = categorize_report(args.report)

    # Also parse git log for commit-level detail. A git failure (e.g. run from
    # outside the repo, or a missing ref) degrades to report-only notes — but it
    # is surfaced, never silently swallowed.
    try:
        subjects = git_log_subjects(args.since, args.until or args.tag)
        commit_cats = categorize_commits(subjects)
    except subprocess.CalledProcessError as exc:
        print(
            f"WARNING: git log {args.since}..{args.tag} failed ({exc}); release notes will omit commit-level detail",
            file=sys.stderr,
        )
        commit_cats = {}

    # Merge: contract changes first, then commit-level entries
    merged: dict[str, list[str]] = defaultdict(list)
    for cat, entries in contract_cats.items():
        merged[cat].extend(entries)
    for cat, entries in commit_cats.items():
        merged[cat].extend(entries)

    section = format_section(
        version=version,
        date=date,
        categories=dict(merged),
        highlights=highlights,
        compare_base=args.since,
        repo_url=args.repo_url,
    )

    _output(section, args)
    return 0


def cmd_from_bootstrap(args: argparse.Namespace) -> int:
    """Write authorized current-state notes without implying a historical assessment."""
    version = args.tag.removeprefix("v")
    date = args.date or git_tag_date(args.tag)
    notes = args.notes_file.read_text(encoding="utf-8").strip()
    if not notes:
        raise ValueError("Bootstrap release notes must describe the current state.")
    section = format_section(
        version=version,
        date=date,
        categories={},
        highlights=(
            "This release establishes a current-state baseline. It does not claim a complete historical compatibility audit.\n\n"
            + notes
        ),
        compare_base=args.since,
        repo_url=args.repo_url,
    )
    _output(section, args)
    return 0


def _output(section: str, args: argparse.Namespace) -> None:
    """Write section to output file and/or prepend to changelog."""
    if args.output:
        args.output.write_text(section + "\n", encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)

    if args.prepend:
        prepend_to_changelog(section, args.prepend)
        print(f"Prepended to {args.prepend}", file=sys.stderr)

    if not args.output and not args.prepend:
        print(section)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Generate changelog sections")
    sub = parser.add_subparsers(dest="command", required=True)

    # Shared args
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--tag", required=True, help="Release tag (e.g. v0.6.0)")
    shared.add_argument("--since", required=True, help="Previous tag (e.g. v0.5.0)")
    shared.add_argument("--until", help="End revision for candidate note generation (defaults to --tag)")
    shared.add_argument("--date", help="Override release date (YYYY-MM-DD)")
    shared.add_argument("--output", type=Path, help="Write section to file")
    shared.add_argument("--prepend", type=Path, help="Prepend section to CHANGELOG.md")
    shared.add_argument(
        "--repo-url",
        default="https://github.com/InstruktAI/TeleClaude",
        help="Repository URL for compare links",
    )

    p_git = sub.add_parser("from-git", parents=[shared], help="Generate from git log")
    p_git.set_defaults(func=cmd_from_git)

    p_rep = sub.add_parser("from-report", parents=[shared], help="Generate from the selected report + git")
    p_rep.add_argument("--report", type=Path, required=True, help="Complete report selected by read_inspector_report")
    p_rep.set_defaults(func=cmd_from_report)

    p_bootstrap = sub.add_parser("from-bootstrap", help="Generate a current-state baseline section")
    p_bootstrap.add_argument("--tag", required=True, help="Bootstrap release tag.")
    p_bootstrap.add_argument("--notes-file", type=Path, required=True, help="Authorized current-state notes.")
    p_bootstrap.add_argument("--since", help="Previous published release tag, if one exists.")
    p_bootstrap.add_argument("--date", help="Override release date (YYYY-MM-DD)")
    p_bootstrap.add_argument("--output", type=Path, help="Write section to file")
    p_bootstrap.add_argument("--prepend", type=Path, help="Prepend section to CHANGELOG.md")
    p_bootstrap.add_argument(
        "--repo-url",
        default="https://github.com/InstruktAI/TeleClaude",
        help="Repository URL for compare links",
    )
    p_bootstrap.set_defaults(func=cmd_from_bootstrap)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
