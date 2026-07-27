"""Replace the Compute Next Version step in release.yaml."""

from __future__ import annotations

import argparse
import tomllib

from teleclaude.git import GitCommandError, Repo
from tools.ci.gha import append_output, repo_root, required_env

ABBREV = "--abbrev=0"
BUMP = "BUMP"
DESCRIPTION = "Compute the next release tag."
LAST_TAG = "last_tag"
MINOR = "minor"
NEXT_TAG = "next_tag"
NO_TAG_PREFIX = "No previous tags — using pyproject.toml version "
NO_TAG_SUFFIX = " as baseline"
PYPROJECT = "pyproject.toml"
SUMMARY_PREFIX = "Computed next version: "
SUMMARY_MIDDLE = " (bump="
SUMMARY_SUFFIX = " from "
TAG_PREFIX = "v"


def latest_tag(repo: Repo) -> str:
    """Read the latest tag or use the project version as the no-tag baseline."""
    try:
        return str(repo.git.describe("--tags", ABBREV)).strip()
    except GitCommandError:
        with (repo_root() / PYPROJECT).open("rb") as pyproject_file:
            project = tomllib.load(pyproject_file)["project"]
        version = project["version"]
        if not isinstance(version, str):
            raise ValueError("pyproject project.version must be a string") from None
        print(NO_TAG_PREFIX + version + NO_TAG_SUFFIX)
        return TAG_PREFIX + version


def next_tag(last_tag: str, bump: str) -> str:
    """Apply the existing minor-or-patch version arithmetic."""
    clean_version = last_tag.removeprefix(TAG_PREFIX).split("-", maxsplit=1)[0]
    major, minor, patch = (int(part) for part in clean_version.split("."))
    if bump == MINOR:
        minor += 1
        patch = 0
    else:
        patch += 1
    return TAG_PREFIX + ".".join((str(major), str(minor), str(patch)))


def main(argv: list[str] | None = None) -> int:
    """Export the release tag outputs consumed by later workflow steps."""
    argparse.ArgumentParser(description=DESCRIPTION).parse_args(argv)
    last = latest_tag(Repo(repo_root()))
    bump = required_env(BUMP)
    following = next_tag(last, bump)
    append_output(LAST_TAG, last)
    append_output(NEXT_TAG, following)
    print(SUMMARY_PREFIX + following + SUMMARY_MIDDLE + bump + SUMMARY_SUFFIX + last + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
