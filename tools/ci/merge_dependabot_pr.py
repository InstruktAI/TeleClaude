"""Replace the trusted Dependabot merge step in lint-test.yaml."""

from __future__ import annotations

import argparse
import os
from typing import Literal

from githubkit import GitHub
from githubkit.auth.token import TokenAuthStrategy
from githubkit.exception import GitHubException

DESCRIPTION = "Merge a Dependabot pull request."
EMPTY_VALUE = ""
GITHUB_REPOSITORY = "GITHUB_REPOSITORY"
GITHUB_TOKEN = "GITHUB_TOKEN"
MERGE_FAILED = "Merging the pull request failed: {}"
MISSING_ENVIRONMENT = "Required environment variable is missing or empty: {}"
PR_NUMBER = "PR_NUMBER"
REPOSITORY_SEPARATOR = "/"
SQUASH: Literal["squash"] = "squash"


def main(argv: list[str] | None = None) -> int:
    """Squash-merge the pull request supplied by the trusted workflow condition."""
    argparse.ArgumentParser(description=DESCRIPTION).parse_args(argv)
    values = {name: os.environ.get(name, EMPTY_VALUE) for name in (GITHUB_REPOSITORY, GITHUB_TOKEN, PR_NUMBER)}
    for name, value in values.items():
        if not value:
            print(MISSING_ENVIRONMENT.format(name))
            return 1
    owner, _separator, repository = values[GITHUB_REPOSITORY].partition(REPOSITORY_SEPARATOR)
    try:
        number = int(values[PR_NUMBER])
        GitHub(TokenAuthStrategy(values[GITHUB_TOKEN])).rest.pulls.merge(owner, repository, number, merge_method=SQUASH)
    except (GitHubException, ValueError) as error:
        print(MERGE_FAILED.format(type(error).__name__))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
