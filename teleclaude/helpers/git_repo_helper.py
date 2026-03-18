"""Clone or update a Git repo checkout.

Automation-only helper. Takes either a full repo URL or explicit host/owner/repo,
clones or pulls into the checkout root, and prints JSON to stdout:
  {"repo_path": "...", "latest_changes": ["..."]}

Artifacts are written elsewhere by the git-repo-scraper skill.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from teleclaude.config.loader import load_global_config
from teleclaude.git import GitCommandError, Repo


def _current_head(repo: Repo) -> str | None:
    try:
        return repo.head.commit.hexsha
    except (ValueError, TypeError):
        return None


DEFAULT_CHECKOUT_ROOT = Path.home() / "Workspace" / "public-repos"


def _dirty_worktree(repo: Repo) -> list[str]:
    status = repo.git.status("--porcelain")
    return [line for line in status.splitlines() if line]


def _default_branch(repo: Repo) -> str:
    """Return the default branch name (main, master, etc.)."""
    for ref in ("refs/remotes/origin/main", "refs/remotes/origin/master"):
        try:
            repo.git.rev_parse("--verify", ref)
            return ref.rsplit("/", 1)[1]
        except GitCommandError:
            continue
    try:
        out = repo.git.remote("show", "origin")
        for line in out.splitlines():
            if "HEAD branch" in line:
                return line.split(":")[-1].strip()
    except GitCommandError:
        pass
    return "main"


def _ensure_on_branch(repo: Repo) -> None:
    """If HEAD is detached or missing, checkout the default branch."""
    try:
        repo.git.symbolic_ref("HEAD")
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
        repo.git.fetch("--all", "--prune")
        repo.git.pull("--ff-only")
        after = _current_head(repo)
        if before and after and before != after:
            commits = repo.git.log("--oneline", f"{before}..{after}")
            return [line for line in commits.splitlines() if line], []
        return [], []

    repo_path.parent.mkdir(parents=True, exist_ok=True)
    Repo.clone_from(repo_url, str(repo_path))
    return [], []


def _load_checkout_root() -> Path:
    config = load_global_config()
    root = config.git.checkout_root
    if not root:
        return DEFAULT_CHECKOUT_ROOT
    return Path(root).expanduser()


def _parse_url(repo_url: str) -> tuple[str, str, str]:
    url = repo_url.strip()
    if url.startswith("git@"):
        # git@host:owner/repo.git
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
    """Parse CLI arguments and emit clone/update results as JSON."""
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
