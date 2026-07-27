"""Replace the Create Tag and Release step in release.yaml."""

from __future__ import annotations

import argparse
import subprocess

from teleclaude.git import Repo
from tools.ci.gha import repo_root, required_env

DESCRIPTION = "Create and publish a release tag."
GH = "gh"
NEXT_TAG = "NEXT_TAG"
NOTES_FILE = "release-notes.md"
ORIGIN = "origin"
PUSH_MAIN = "HEAD:main"
RELEASE = "release"
RELEASE_CREATE = "create"
TITLE = "--title"
NOTES_FILE_FLAG = "--notes-file"


def main(argv: list[str] | None = None) -> int:
    """Create the release tag, push it, and publish the GitHub release."""
    argparse.ArgumentParser(description=DESCRIPTION).parse_args(argv)
    tag = required_env(NEXT_TAG)
    repo = Repo(repo_root())
    repo.create_tag(tag)
    repo.git.push(ORIGIN, PUSH_MAIN, tag)
    # GitHub release publication has no project helper or native Python binding.
    subprocess.run([GH, RELEASE, RELEASE_CREATE, tag, TITLE, tag, NOTES_FILE_FLAG, NOTES_FILE], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
