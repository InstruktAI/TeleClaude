"""Replace the Compute Next Version step in release.yaml."""

from __future__ import annotations

import argparse
import re
from enum import StrEnum

from tools.ci.gha import append_output, required_env

BUMP = "BUMP"
BASELINE_TAG = "BASELINE_TAG"
DESCRIPTION = "Compute the next release tag."
LAST_TAG = "last_tag"
NEXT_TAG = "next_tag"
SUMMARY_PREFIX = "Computed next version: "
SUMMARY_MIDDLE = " (bump="
SUMMARY_SUFFIX = " from "
TAG_PREFIX = "v"
VERSION_SEPARATOR = "."
SUMMARY_END = ")"
INVALID_BASELINE = "BASELINE_TAG must be a semantic release tag in MAJOR.MINOR.PATCH form."
INVALID_BUMP = "BUMP must be patch or minor."
SEMANTIC_TAG_PATTERN = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


class ReleaseBump(StrEnum):
    """Supported release increments under the current pre-major policy."""

    PATCH = "patch"
    MINOR = "minor"


def next_tag(last_tag: str, bump: ReleaseBump) -> str:
    """Apply the existing minor-or-patch version arithmetic."""
    if SEMANTIC_TAG_PATTERN.fullmatch(last_tag) is None:
        raise ValueError(INVALID_BASELINE)
    parts = last_tag.removeprefix(TAG_PREFIX).split(VERSION_SEPARATOR)
    major, minor, patch = (int(part) for part in parts)
    if bump is ReleaseBump.MINOR:
        minor += 1
        patch = 0
    elif bump is ReleaseBump.PATCH:
        patch += 1
    else:
        raise ValueError(INVALID_BUMP)
    return TAG_PREFIX + VERSION_SEPARATOR.join((str(major), str(minor), str(patch)))


def main(argv: list[str] | None = None) -> int:
    """Export the release tag outputs consumed by later workflow steps."""
    argparse.ArgumentParser(description=DESCRIPTION).parse_args(argv)
    last = required_env(BASELINE_TAG)
    try:
        bump = ReleaseBump(required_env(BUMP))
    except ValueError:
        raise ValueError(INVALID_BUMP) from None
    following = next_tag(last, bump)
    append_output(LAST_TAG, last)
    append_output(NEXT_TAG, following)
    print(SUMMARY_PREFIX + following + SUMMARY_MIDDLE + bump + SUMMARY_SUFFIX + last + SUMMARY_END)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
