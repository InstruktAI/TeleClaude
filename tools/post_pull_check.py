#!/usr/bin/env python3
"""Post-pull checkpoint — reuses the checkpoint file categorization engine.

Run from the project root after pulling to determine what actions are needed
(daemon restart, dependency install, etc.). Uses git diff to identify changed
files and the existing CHECKPOINT_FILE_CATEGORIES to map them to instructions.

Exit codes:
  0 — actions printed (or nothing actionable)
  1 — git error or unexpected failure

Usage:
  python tools/post_pull_check.py              # defaults to HEAD@{1}..HEAD
  python tools/post_pull_check.py <from>..<to>  # explicit ref range
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from teleclaude.checkpoint_model import load_checkpoint_model, triggered_action_ids  # noqa: E402
from teleclaude.git import GitCommandError, Repo  # noqa: E402


def _diff_files(repo_path: str, ref_range: str) -> list[str]:
    """Return files changed in the given ref range."""
    repo = Repo(repo_path, search_parent_directories=True)
    output = repo.git.diff("--name-only", ref_range)
    return [line.strip() for line in output.splitlines() if line.strip()]


def main() -> None:
    repo_path = str(Path.cwd())
    ref_range = sys.argv[1] if len(sys.argv) > 1 else "HEAD@{1}..HEAD"

    try:
        files = _diff_files(repo_path, ref_range)
    except (GitCommandError, OSError) as exc:
        print(f"post_pull_check: git diff failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not files:
        return

    model = load_checkpoint_model(repo_path)
    owed = sorted(
        (
            model.actions[action_id]
            for action_id in triggered_action_ids(files, model)
            if action_id in model.actions and model.actions[action_id].main_only
        ),
        key=lambda action: (action.precedence, action.id),
    )

    if not owed:
        return

    print(f"Changed: {', '.join(action.id for action in owed)}")
    print("Required actions:")
    for i, action in enumerate(owed, 1):
        print(f"  {i}. {action.run.replace('{window}', '2m')}")


if __name__ == "__main__":
    main()
