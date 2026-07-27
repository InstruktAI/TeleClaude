"""Replace the version-bump commit step in release.yaml."""

from __future__ import annotations

import argparse
import re

from teleclaude.git import Repo
from tools.ci.gha import repo_root, required_env

AUTHOR_EMAIL = "github-actions[bot]@users.noreply.github.com"
AUTHOR_NAME = "github-actions[bot]"
CHANGELOG = "CHANGELOG.md"
CLEAN_TAG_PREFIX = "v"
COMMIT_PREFIX = "chore: bump version to "
COMMIT_SUFFIX = " [skip ci]"
DESCRIPTION = "Commit generated release artifacts."
MANIFESTS = ("manifests/cli-surface.md", "manifests/events.md", "manifests/config.md")
NEXT_TAG = "NEXT_TAG"
PYPROJECT = "pyproject.toml"
VERSION_LINE = re.compile(r'^version = ".*"$', re.MULTILINE)
VERSION_REPLACEMENT = 'version = "{version}"'


def update_version(version: str) -> None:
    """Replace the project version line using the workflow's exact target."""
    pyproject = repo_root() / PYPROJECT
    content = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(VERSION_LINE.sub(VERSION_REPLACEMENT.format(version=version), content), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Create the release artifact commit under the Actions bot identity."""
    argparse.ArgumentParser(description=DESCRIPTION).parse_args(argv)
    version = required_env(NEXT_TAG).removeprefix(CLEAN_TAG_PREFIX)
    update_version(version)
    repo = Repo(repo_root())
    repo.config_writer().set_value("user", "name", AUTHOR_NAME).release()
    repo.config_writer().set_value("user", "email", AUTHOR_EMAIL).release()
    repo.index.add([PYPROJECT, *MANIFESTS, CHANGELOG])
    repo.index.commit(COMMIT_PREFIX + version + COMMIT_SUFFIX)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
