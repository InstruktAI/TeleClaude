"""Replace the Compute Next Version step in release.yaml."""

from __future__ import annotations

import argparse
from enum import StrEnum

from tools.ci.gha import append_output, required_env
from tools.release.attempt import stable_version_components

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
INVALID_BUMP = "BUMP must be patch, minor or major."
MAJOR_BEFORE_ONE = (
    "A major bump needs a baseline whose major is positive; the first 1.0 is published with an explicit version."
)
PRE_RELEASE_MAJOR = 0


class ReleaseBump(StrEnum):
    """Supported release increments: a major increment applies only from a positive major baseline."""

    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


def next_tag(last_tag: str, bump: ReleaseBump) -> str:
    """Apply the patch, minor or major increment to the baseline; a major needs a positive baseline major."""
    try:
        major, minor, patch = stable_version_components(last_tag)
    except ValueError:
        raise ValueError(INVALID_BASELINE) from None
    if bump is ReleaseBump.MAJOR:
        if major == PRE_RELEASE_MAJOR:
            raise ValueError(MAJOR_BEFORE_ONE)
        major += 1
        minor = 0
        patch = 0
    elif bump is ReleaseBump.MINOR:
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
