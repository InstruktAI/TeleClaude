#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Assemble a frozen release section and verify complete generated commit notes."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import cast

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from teleclaude.git import GitCommandError, Repo  # noqa: E402

_COMMIT_NOTE_ENTRY_PATTERN = re.compile(
    r"^- \[([0-9a-f]{7})\]\(https://github\.com/InstruktAI/TeleClaude/commit/([0-9a-f]{40})\) ?(.*)$"
)
_COMMIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_SHA_LENGTH = 7
_UTF8 = "utf-8"
_SECTION_HEADING = "## ["
_INVALID_SHA = "The captured release source or baseline is not a full Git commit id."
_CHECKOUT_MISMATCH = "The candidate checkout does not match the captured release source."
_RANGE_UNAVAILABLE = "The captured Git range could not be resolved for commit-note verification."
_ENTRY_INVALID = "The generated commit notes do not use the canonical linked-entry format."
_COVERAGE_MISMATCH = "The generated commit-note identities do not match the complete captured Git range."
_HEAD_REFERENCE = "HEAD"
_NEWLINE = "\n"
_RANGE_SEPARATOR = ".."
_EMPTY = ""
_SUMMARY_PREFIX = "> "
_SECTION_HEADING_TEMPLATE = "## [{}] - {}"
_DEFAULT_REPOSITORY_URL = "https://github.com/InstruktAI/TeleClaude"
_COMPARE_LINK_TEMPLATE = "**Full diff:** [{}...v{}]({}/compare/{}...v{})"
_INITIAL_CHANGELOG_CONTENT = (
    "# Changelog\n\n"
    "All notable changes to TeleClaude are documented in this file.\n\n"
    "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).\n"
)
_VERIFICATION_SUMMARY_TEMPLATE = "Verified complete commit notes for {} commits"
_CLI_DESCRIPTION = "Assemble release sections and verify generated commit notes"
_COMMAND_DESTINATION = "command"
_VERIFY_COMMAND = "verify-commit-notes"
_VERIFY_HELP = "Verify complete linked notes against captured Git range"
_SOURCE_OPTION = "--source"
_BASELINE_OPTION = "--baseline"
_NOTES_OPTION = "--notes"
_REVERSE_LOG_OPTION = "--reverse"
MAX_RELEASE_BODY_BYTES = 128 * 1024


def verify_commit_notes(
    repository_root: Path,
    source_sha: str,
    baseline_sha: str | None,
    notes_path: Path,
    *,
    require_head: bool = True,
) -> list[str]:
    """Require one canonical commit-note link for every identity in the captured Git range."""
    if _COMMIT_SHA_PATTERN.fullmatch(source_sha) is None or (
        baseline_sha is not None and _COMMIT_SHA_PATTERN.fullmatch(baseline_sha) is None
    ):
        raise ValueError(_INVALID_SHA)
    repo = Repo(repository_root)
    try:
        source_commit = repo.commit(source_sha).hexsha
        if require_head and repo.commit(_HEAD_REFERENCE).hexsha != source_sha:
            raise ValueError(_CHECKOUT_MISMATCH)
        revision = source_commit if baseline_sha is None else baseline_sha + _RANGE_SEPARATOR + source_commit
        expected = str(repo.git.rev_list(_REVERSE_LOG_OPTION, revision)).splitlines()
    except GitCommandError:
        raise ValueError(_RANGE_UNAVAILABLE) from None

    actual: list[str] = []
    for line in notes_path.read_text(encoding=_UTF8).splitlines():
        if not line:
            continue
        match = _COMMIT_NOTE_ENTRY_PATTERN.fullmatch(line)
        if match is None:
            raise ValueError(_ENTRY_INVALID)
        abbreviation, commit_sha = match.groups()[:2]
        if abbreviation != commit_sha[:_SHA_LENGTH]:
            raise ValueError(_ENTRY_INVALID)
        actual.append(commit_sha)
    if Counter(actual) != Counter(expected) or len(actual) != len(set(actual)):
        raise ValueError(_COVERAGE_MISMATCH)
    return actual


def assemble_section(
    version: str,
    date: str,
    notes: str,
    summary: str | None,
    compare_base: str | None,
    repo_url: str = _DEFAULT_REPOSITORY_URL,
) -> str:
    """Add release metadata around exact generated entries, with summary confined to a quote."""
    lines = [_SECTION_HEADING_TEMPLATE.format(version, date)]
    if summary:
        lines.append(_EMPTY)
        # Quoting every line, including empty ones, keeps untrusted report text out of
        # the changelog's top-level section namespace while preserving its text.
        lines.extend(_SUMMARY_PREFIX + line for line in summary.strip().splitlines())
    note_lines = notes.rstrip(_NEWLINE).splitlines()
    if note_lines and any(line for line in note_lines):
        lines.append(_EMPTY)
        lines.extend(note_lines)
    if compare_base:
        lines.extend(
            [
                _EMPTY,
                _COMPARE_LINK_TEMPLATE.format(compare_base, version, repo_url, compare_base, version),
            ]
        )
    return _NEWLINE.join(lines)


def prepend_to_changelog(section: str, path: Path) -> None:
    """Prepend a version section to CHANGELOG.md after its existing document header."""
    if path.exists():
        content = path.read_text(encoding=_UTF8)
    else:
        content = _INITIAL_CHANGELOG_CONTENT
    lines = content.split(_NEWLINE)
    insert_at = next((index for index, line in enumerate(lines) if line.startswith(_SECTION_HEADING)), len(lines))
    path.write_text(_NEWLINE.join(lines[:insert_at] + [section, _EMPTY] + lines[insert_at:]), encoding=_UTF8)


def _verify(args: argparse.Namespace) -> int:
    commit_ids = verify_commit_notes(_REPO_ROOT, args.source, args.baseline, args.notes)
    print(_VERIFICATION_SUMMARY_TEMPLATE.format(len(commit_ids)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=_CLI_DESCRIPTION)
    subparsers = parser.add_subparsers(dest=_COMMAND_DESTINATION, required=True)
    verify = subparsers.add_parser(_VERIFY_COMMAND, help=_VERIFY_HELP)
    verify.add_argument(_SOURCE_OPTION, required=True)
    verify.add_argument(_BASELINE_OPTION)
    verify.add_argument(_NOTES_OPTION, type=Path, required=True)
    verify.set_defaults(func=_verify)
    args = parser.parse_args(argv)
    return cast(int, args.func(args))


if __name__ == "__main__":
    sys.exit(main())
