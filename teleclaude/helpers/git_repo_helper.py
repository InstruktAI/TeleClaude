"""Clone or update a Git repo checkout.

Automation-only helper. Takes either a full repo URL or explicit host/owner/repo,
clones or pulls into the checkout root, and prints JSON to stdout:
  {"repo_path": "...", "latest_changes": ["..."]}

Artifacts are written elsewhere by the git-repo-scraper skill.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import yaml


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def _git_output(cmd: list[str], cwd: Path) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True).strip()


def _current_head(repo_path: Path) -> str | None:
    try:
        return _git_output(["git", "rev-parse", "HEAD"], cwd=repo_path)
    except subprocess.CalledProcessError:
        return None


DEFAULT_CHECKOUT_ROOT = Path.home() / "Workspace" / "public-repos"


def _dirty_worktree(repo_path: Path) -> list[str]:
    status = _git_output(["git", "status", "--porcelain"], cwd=repo_path)
    return [line for line in status.splitlines() if line]


def _default_branch(repo_path: Path) -> str:
    """Return the default branch name (main, master, etc.)."""
    for ref in ("refs/remotes/origin/main", "refs/remotes/origin/master"):
        try:
            _git_output(["git", "rev-parse", "--verify", ref], cwd=repo_path)
            return ref.rsplit("/", 1)[1]
        except subprocess.CalledProcessError:
            continue
    try:
        out = _git_output(["git", "remote", "show", "origin"], cwd=repo_path)
        for line in out.splitlines():
            if "HEAD branch" in line:
                return line.split(":")[-1].strip()
    except subprocess.CalledProcessError:
        pass
    return "main"


def _ensure_on_branch(repo_path: Path) -> None:
    """If HEAD is detached or missing, checkout the default branch."""
    try:
        _git_output(["git", "symbolic-ref", "HEAD"], cwd=repo_path)
    except subprocess.CalledProcessError:
        branch = _default_branch(repo_path)
        _run(["git", "checkout", branch], cwd=repo_path)


def _ensure_repo(repo_url: str, repo_path: Path) -> tuple[list[str], list[str]]:
    """Ensure repo exists; return (changes, dirty_changes)."""
    if repo_path.exists() and (repo_path / ".git").exists():
        _ensure_on_branch(repo_path)
        dirty = _dirty_worktree(repo_path)
        if dirty:
            return [], dirty
        before = _current_head(repo_path)
        _run(["git", "fetch", "--all", "--prune"], cwd=repo_path)
        _run(["git", "pull", "--ff-only"], cwd=repo_path)
        after = _current_head(repo_path)
        if before and after and before != after:
            commits = _git_output(["git", "log", "--oneline", f"{before}..{after}"], cwd=repo_path)
            return [line for line in commits.splitlines() if line], []
        return [], []

    repo_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", repo_url, str(repo_path)])
    return [], []


def _load_checkout_root() -> Path:
    config_path = Path.home() / ".teleclaude" / "config" / "teleclaude.yml"
    if not config_path.exists():
        return DEFAULT_CHECKOUT_ROOT
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return DEFAULT_CHECKOUT_ROOT
    gh = raw.get("git", {}) if isinstance(raw, dict) else {}
    root = gh.get("checkout_root") if isinstance(gh, dict) else None
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
