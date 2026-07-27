"""Replace the Check for relevant changes step in sandbox-runner.yaml."""

from __future__ import annotations

import argparse

from teleclaude.git import GitCommandError, Repo
from tools.ci.gha import append_output, emit_error, repo_root, required_env

CHANGED = "changed"
DESCRIPTION = "Detect sandbox-image source changes."
FALSE = "false"
HEAD_COMMIT = "HEAD_COMMIT"
HEAD_REF = "HEAD"
PREVIOUS_SUFFIX = "~1"
TRUE = "true"
WATCHED_PATHS = ("teleclaude/events/", "docker/sandbox-runner/")
UNRESOLVABLE_PREFIX = "Could not resolve previous ref: "


def main(argv: list[str] | None = None) -> int:
    """Export whether the prior commit changed the sandbox image inputs."""
    argparse.ArgumentParser(description=DESCRIPTION).parse_args(argv)
    previous = required_env(HEAD_COMMIT) + PREVIOUS_SUFFIX
    try:
        output = str(Repo(repo_root()).git.diff("--name-only", previous, HEAD_REF, "--", *WATCHED_PATHS))
    except GitCommandError:
        emit_error(UNRESOLVABLE_PREFIX + previous)
        return 1
    append_output(CHANGED, TRUE if output.strip() else FALSE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
