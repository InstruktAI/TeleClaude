"""Replace the trusted Dependabot merge step in lint-test.yaml."""

from __future__ import annotations

import argparse
import os
import subprocess

EMPTY_VALUE = ""
DESCRIPTION = "Merge a Dependabot pull request."
GH = "gh"
MERGE = "merge"
MISSING_PR_URL = "Required environment variable is missing or empty: PR_URL"
PR = "pr"
PR_URL = "PR_URL"
SQUASH = "--squash"


def main(argv: list[str] | None = None) -> int:
    """Merge the pull request supplied by the trusted workflow condition."""
    argparse.ArgumentParser(description=DESCRIPTION).parse_args(argv)
    url = os.environ.get(PR_URL, EMPTY_VALUE)
    if not url:
        print(MISSING_PR_URL)
        return 1
    # GitHub CLI is the supported interface for GitHub pull-request merging.
    subprocess.run([GH, PR, MERGE, SQUASH, url], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
