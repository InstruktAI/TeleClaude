"""Replace the Prepare Analysis Context step in release.yaml."""

from __future__ import annotations

import argparse
from difflib import unified_diff

from teleclaude.git import GitCommandError, Repo
from tools.ci.export_manifests import export_manifests
from tools.ci.gha import append_env, repo_root

ABBREV = "--abbrev=0"
CLI_HEADING = "## CLI Surface\n"
COMMIT_LOG_HEADING = "# COMMIT LOG\n"
CONFIG_HEADING = "## Config\n"
CURRENT_MANIFESTS_HEADING = "# CURRENT MANIFESTS\n"
DESCRIPTION = "Build the release analysis prompt."
DIFFSTAT_HEADING = "# DIFFSTAT\n"
DIFF_FENCE_END = "```\n\n"
DIFF_FENCE_START = "```diff\n"
DIFFSTAT_FIRST_RELEASE = "First release — diffstat not applicable."
EVENTS_HEADING = "## Events\n"
FIRST_RELEASE = "First release — all manifest items are new additions.\n"
GITHUB_ENV = "GITHUB_ENV"
LAST_TAG = "LAST_TAG"
MANIFEST_DIFF_HEADING = "# MANIFEST DIFF\n"
MANIFEST_NAMES = ("cli-surface", "events", "config")
MANIFESTS_DIRECTORY = "manifests"
NEWLINE = "\n"
NO_BASELINE_PREFIX = "No baseline at "
NO_BASELINE_SUFFIX = " — treating all items as new.\n\n"
NO_CHANGES = "No changes.\n\n"
PROMPT_FILE = "release-prompt.txt"
PROMPT_PREFIX = "Prompt size: "
PROMPT_SUFFIX = " bytes"
RELEASE_PROMPT = "docs/project/spec/release-inspector-prompt.md"


def latest_tag(repo: Repo) -> str:
    """Return the newest release tag or the shell body's empty fallback."""
    try:
        return str(repo.git.describe("--tags", ABBREV)).strip()
    except GitCommandError:
        return ""


def baseline(repo: Repo, tag: str, manifest_name: str) -> str:
    """Read a manifest from the release tag or return the missing-baseline value."""
    source = tag + ":" + MANIFESTS_DIRECTORY + "/" + manifest_name + ".md"
    try:
        return str(repo.git.show(source))
    except GitCommandError:
        return ""


def manifest_diff(repo: Repo, tag: str) -> str:
    """Produce the release-prompt manifest comparison sections."""
    if not tag:
        return FIRST_RELEASE
    sections: list[str] = []
    for name in MANIFEST_NAMES:
        manifest_name = name + ".md"
        previous = baseline(repo, tag, name)
        if not previous:
            sections.append("### " + manifest_name + NEWLINE + NO_BASELINE_PREFIX + tag + NO_BASELINE_SUFFIX)
            continue
        current = (repo_root() / MANIFESTS_DIRECTORY / manifest_name).read_text(encoding="utf-8")
        lines = list(
            unified_diff(
                previous.splitlines(keepends=True),
                current.splitlines(keepends=True),
                fromfile="a/manifests/" + manifest_name,
                tofile="b/manifests/" + manifest_name,
            )
        )
        if not lines:
            sections.append("### " + manifest_name + NEWLINE + NO_CHANGES)
            continue
        sections.append("### " + manifest_name + NEWLINE + DIFF_FENCE_START + "".join(lines) + DIFF_FENCE_END)
    return "".join(sections)


def git_log(repo: Repo, tag: str) -> str:
    """Return the commit log selected by the shell body."""
    return str(repo.git.log("--oneline", tag + "..HEAD")) if tag else str(repo.git.log("--oneline", "-100"))


def diffstat(repo: Repo, tag: str) -> str:
    """Return the release diffstat or its first-release text."""
    return str(repo.git.diff("--stat", tag + "..HEAD")) if tag else DIFFSTAT_FIRST_RELEASE


def main(argv: list[str] | None = None) -> int:
    """Generate the release prompt used by the analysis lanes."""
    argparse.ArgumentParser(description=DESCRIPTION).parse_args(argv)
    root = repo_root()
    repo = Repo(root)
    tag = latest_tag(repo)
    append_env(LAST_TAG, tag)
    export_manifests()
    prompt = "".join(
        (
            (root / RELEASE_PROMPT).read_text(encoding="utf-8"),
            NEWLINE,
            MANIFEST_DIFF_HEADING,
            manifest_diff(repo, tag),
            CURRENT_MANIFESTS_HEADING,
            CLI_HEADING,
            (root / MANIFESTS_DIRECTORY / "cli-surface.md").read_text(encoding="utf-8"),
            NEWLINE,
            EVENTS_HEADING,
            (root / MANIFESTS_DIRECTORY / "events.md").read_text(encoding="utf-8"),
            NEWLINE,
            CONFIG_HEADING,
            (root / MANIFESTS_DIRECTORY / "config.md").read_text(encoding="utf-8"),
            NEWLINE,
            COMMIT_LOG_HEADING,
            git_log(repo, tag),
            NEWLINE,
            DIFFSTAT_HEADING,
            diffstat(repo, tag),
            NEWLINE,
        )
    )
    destination = root / PROMPT_FILE
    destination.write_text(prompt, encoding="utf-8")
    print(PROMPT_PREFIX + str(destination.stat().st_size) + PROMPT_SUFFIX)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
