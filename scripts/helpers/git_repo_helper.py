#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "GitPython",
# ]
# ///
"""Clone or update a Git repo checkout.

Automation-only helper. Takes either a full repo URL or explicit host/owner/repo,
clones or pulls into the checkout root, and prints JSON to stdout:
  {"repo_path": "...", "latest_changes": ["..."]}

Artifacts are written elsewhere by the git-repo-scraper skill.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from git import Repo
from git import refresh as refresh_git
from git.exc import GitCommandError

_GIT_EXECUTABLE_NAME = "git"
_REAL_GIT_ERROR = "real git binary not found in PATH"
_TELEC_COMMAND = "telec"
_CONFIG_COMMAND = "config"
_GLOBAL_COMMAND = "global"
_GET_COMMAND = "get"
_JSON_FORMAT_FLAG = "--format"
_JSON_FORMAT = "json"
_GLOBAL_SECTION_KEY = "global"
_CHECKOUT_ROOT_KEY = "checkout_root"
_EMPTY_TEXT = ""
_CONFIG_QUERY_COMMAND = (
    _TELEC_COMMAND,
    _CONFIG_COMMAND,
    _GLOBAL_COMMAND,
    _GET_COMMAND,
    _JSON_FORMAT_FLAG,
    _JSON_FORMAT,
)
_CONFIG_READ_FAILURE = "ERROR: unable to read the global checkout-root setting through Config: {detail}"
_CONFIG_EXECUTION_FAILURE = "ERROR: unable to run the Config CLI for the global checkout-root setting: {error}"
_CONFIG_RESPONSE_INVALID = (
    "ERROR: Config returned an invalid global checkout-root response; expected a JSON global object"
)
_CONFIG_OUTPUT_EMPTY = "Config returned no global checkout-root setting"
_NEUTRAL_CWD = Path(Path(__file__).resolve().anchor)
_REMOTE_MAIN_REF = "refs/remotes/origin/main"
_REMOTE_MASTER_REF = "refs/remotes/origin/master"
_GIT_VERIFY = "--verify"
_GIT_PORCELAIN = "--porcelain"
_GIT_HEAD = "HEAD"
_GIT_ALL = "--all"
_GIT_PRUNE = "--prune"
_GIT_FF_ONLY = "--ff-only"
_GIT_ONELINE = "--oneline"
_GIT_REMOTE_SHOW = "show"
_GIT_ORIGIN = "origin"
_HEAD_BRANCH_LABEL = "HEAD branch"
_GIT_BRANCH_SEPARATOR = ":"
_MAIN_BRANCH = "main"


def _real_git_executable() -> Path:
    """Resolve Git outside TeleClaude's command wrapper for this standalone process."""
    executable = shutil.which(_GIT_EXECUTABLE_NAME, path=os.defpath)
    if executable is None:
        raise FileNotFoundError(_REAL_GIT_ERROR)
    return Path(executable)


# The standalone command runs outside the repo package import path, so it resolves
# the same real Git executable that the in-repo Git owner selects.
refresh_git(str(_real_git_executable()))


def _current_head(repo: Repo) -> str | None:
    try:
        return str(repo.head.commit.hexsha)
    except (ValueError, TypeError, GitCommandError):
        return None


DEFAULT_CHECKOUT_ROOT = Path.home() / "Workspace" / "public-repos"


def _dirty_worktree(repo: Repo) -> list[str]:
    status = repo.git.status(_GIT_PORCELAIN)
    return [line for line in status.splitlines() if line]


def _default_branch(repo: Repo) -> str:
    """Return the default branch name (main, master, etc.)."""
    for ref in (_REMOTE_MAIN_REF, _REMOTE_MASTER_REF):
        try:
            repo.git.rev_parse(_GIT_VERIFY, ref)
            return ref.rsplit("/", 1)[1]
        except GitCommandError:
            continue
    # Fallback: ask remote HEAD
    try:
        out = str(repo.git.remote(_GIT_REMOTE_SHOW, _GIT_ORIGIN))
        for line in out.splitlines():
            if _HEAD_BRANCH_LABEL in line:
                return line.split(_GIT_BRANCH_SEPARATOR)[-1].strip()
    except GitCommandError:
        pass
    return _MAIN_BRANCH


def _ensure_on_branch(repo: Repo) -> None:
    """If HEAD is detached or missing, checkout the default branch."""
    try:
        repo.git.symbolic_ref(_GIT_HEAD)
    except GitCommandError:
        branch = _default_branch(repo)
        repo.git.checkout(branch)


def _ensure_repo(repo_url: str, repo_path: Path) -> tuple[list[str], list[str]]:
    """Ensure repo exists; return (changes, dirty_changes)."""
    if repo_path.exists() and (repo_path / ".git").exists():
        repo = Repo(repo_path)
        _ensure_on_branch(repo)
        dirty = _dirty_worktree(repo)
        if dirty:
            return [], dirty
        before = _current_head(repo)
        repo.git.fetch(_GIT_ALL, _GIT_PRUNE)
        repo.git.pull(_GIT_FF_ONLY)
        after = _current_head(repo)
        if before and after and before != after:
            commits = repo.git.log(_GIT_ONELINE, f"{before}..{after}")
            return [line for line in commits.splitlines() if line], []
        return [], []

    repo_path.parent.mkdir(parents=True, exist_ok=True)
    Repo.clone_from(repo_url, str(repo_path))
    return [], []


def _load_checkout_root() -> Path:
    # No first-party Config API is importable in this isolated PEP 723 runtime, so use Config's published CLI.
    try:
        result = subprocess.run(
            _CONFIG_QUERY_COMMAND,
            capture_output=True,
            check=False,
            cwd=_NEUTRAL_CWD,
            text=True,
        )
    except OSError as exc:
        raise SystemExit(_CONFIG_EXECUTION_FAILURE.format(error=exc)) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or _CONFIG_OUTPUT_EMPTY
        raise SystemExit(_CONFIG_READ_FAILURE.format(detail=detail))
    try:
        response: object = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(_CONFIG_RESPONSE_INVALID) from exc
    if not isinstance(response, dict):
        raise SystemExit(_CONFIG_RESPONSE_INVALID)
    global_config = response.get(_GLOBAL_SECTION_KEY)
    if not isinstance(global_config, dict):
        raise SystemExit(_CONFIG_RESPONSE_INVALID)
    root = global_config.get(_CHECKOUT_ROOT_KEY)
    if root is None or root == _EMPTY_TEXT:
        return DEFAULT_CHECKOUT_ROOT
    if not isinstance(root, str):
        raise SystemExit(_CONFIG_RESPONSE_INVALID)
    return Path(root).expanduser()


def _parse_url(repo_url: str) -> tuple[str, str, str]:
    url = repo_url.strip()
    if url.startswith("git@"):
        host_part, path = url.split("@", 1)[1].split(":", 1)
        host = host_part
    else:
        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path.lstrip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    parts = path.split("/")
    if len(parts) < 2:
        raise ValueError(f"Could not parse owner/repo from: {repo_url}")
    owner, repo = parts[0], parts[1]
    return host, owner, repo


def _build_url(host: str, owner: str, repo: str) -> str:
    return f"https://{host}/{owner}/{repo}.git"


def main() -> None:
    parser = argparse.ArgumentParser(description="Clone or update Git repo.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="Full repo URL")
    group.add_argument("--host", help="Repo host (e.g., github.com)")
    parser.add_argument("--owner", help="Repo owner")
    parser.add_argument("--repo", help="Repo name")
    args = parser.parse_args()

    if args.url:
        host, owner, repo = _parse_url(args.url)
        repo_url = args.url
    else:
        if not args.owner or not args.repo:
            raise SystemExit("ERROR: --host requires --owner and --repo")
        host, owner, repo = args.host, args.owner, args.repo
        repo_url = _build_url(host, owner, repo)

    checkout_root = _load_checkout_root()
    repo_path = checkout_root / host / owner / repo
    changes, dirty_changes = _ensure_repo(repo_url, repo_path)
    payload = {
        "repo_path": str(repo_path),
        "latest_changes": changes,
        "dirty_changes": dirty_changes,
    }
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
