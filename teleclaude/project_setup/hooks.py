"""Pre-commit hook installation for TeleClaude docs check."""

from pathlib import Path

# Marker strings used for idempotent hook block insertion.
DOCS_CHECK_MARKER = "teleclaude-docs-check"
STASH_PREVENTION_MARKER = "teleclaude-stash-prevention"
_OLD_OVERLAP_MARKER = "teleclaude-overlap-guard"

# Guard that blocks commits when ANY unstaged changes to tracked files exist.
# WHY: pre-commit's staged_files_only.py saves unstaged changes as a patch, runs
# `git checkout -- .` (nukes working tree), runs hooks, then `git apply` to restore.
# When apply fails (deleted files, conflicts with hook formatting), unstaged changes
# are permanently lost. By requiring a clean working tree, _unstaged_changes_cleared()
# always takes the safe retcode==0 path (no patch, no checkout, no data loss).
STASH_PREVENTION_BLOCK = f"""
# {STASH_PREVENTION_MARKER}: block commits with unstaged changes to tracked files
_teleclaude_unstaged="$(git diff --name-only)"
if [ -n "$_teleclaude_unstaged" ]; then
  echo "ERROR: unstaged changes to tracked files detected."
  echo "Pre-commit would stash these and risk losing them."
  echo ""
  echo "Unstaged files:"
  printf '  %s\\n' $_teleclaude_unstaged
  echo ""
  echo "Stage all changes (git add) or commit in separate steps."
  exit 1
fi
"""

# Check command that detects hardcoded HOME paths in staged .md files
PRECOMMIT_CHECK = (
    "git diff --cached --name-only --diff-filter=ACM | "
    "grep '\\.md$' | "
    'xargs -r grep -l "@/Users/\\|@/home/" && '
    "echo \"ERROR: Hardcoded HOME paths found in docs. Run 'telec init' to set up filters.\" && "
    "exit 1 || true"
)


def install_precommit_hook(project_root: Path) -> None:
    """Install pre-commit hook to catch hardcoded HOME paths.

    Detects the hook system in use (pre-commit framework, Husky, or raw git hooks)
    and adds the check appropriately.

    Args:
        project_root: Path to the project root directory.
    """
    precommit_config = project_root / ".pre-commit-config.yaml"
    husky_dir = project_root / ".husky"
    git_hooks_dir = project_root / ".git" / "hooks"
    precommit_hook_file = git_hooks_dir / "pre-commit"

    if precommit_config.exists():
        _add_precommit_framework_hook(precommit_config)
        _ensure_precommit_entrypoint_guard(precommit_hook_file)
    elif husky_dir.exists():
        _add_husky_hook(husky_dir)
    elif git_hooks_dir.exists():
        _add_raw_git_hook(git_hooks_dir)
    else:
        print("telec init: no git hooks directory found, skipping hook installation.")


def _add_precommit_framework_hook(config_path: Path) -> None:
    """Add hook to pre-commit framework config."""
    import yaml

    content = config_path.read_text(encoding="utf-8")

    if DOCS_CHECK_MARKER in content:
        print("telec init: pre-commit hook already configured.")
        return

    try:
        config = yaml.safe_load(content) or {}
    except Exception:
        print("telec init: failed to parse .pre-commit-config.yaml, skipping hook.")
        return

    if "repos" not in config:
        config["repos"] = []

    teleclaude_hook = {
        "repo": "local",
        "hooks": [
            {
                "id": "teleclaude-docs-check",
                "name": "Check for hardcoded HOME paths in docs",
                "entry": "bash -c",
                "args": [PRECOMMIT_CHECK],
                "language": "system",
                "files": r"\.md$",
                "pass_filenames": False,
            }
        ],
    }
    config["repos"].append(teleclaude_hook)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)
    print("telec init: pre-commit hook added to .pre-commit-config.yaml.")


def _add_husky_hook(husky_dir: Path) -> None:
    """Add check to Husky pre-commit hook."""
    hook_file = husky_dir / "pre-commit"

    if not hook_file.exists():
        hook_file.write_text("#!/bin/bash\n", encoding="utf-8")

    changed = False
    changed |= _append_block_if_missing(hook_file, STASH_PREVENTION_MARKER, STASH_PREVENTION_BLOCK)
    changed |= _append_block_if_missing(
        hook_file,
        DOCS_CHECK_MARKER,
        f"""
# {DOCS_CHECK_MARKER}: Reject hardcoded HOME paths
{PRECOMMIT_CHECK}
""",
    )

    hook_file.chmod(hook_file.stat().st_mode | 0o111)
    if changed:
        print("telec init: husky pre-commit hook updated.")
    else:
        print("telec init: husky hook already configured.")


def _add_raw_git_hook(hooks_dir: Path) -> None:
    """Add or create raw git pre-commit hook."""
    hook_file = hooks_dir / "pre-commit"

    if not hook_file.exists():
        content = """#!/bin/bash
"""
        hook_file.write_text(content, encoding="utf-8")

    changed = False
    changed |= _append_block_if_missing(hook_file, STASH_PREVENTION_MARKER, STASH_PREVENTION_BLOCK)
    changed |= _append_block_if_missing(
        hook_file,
        DOCS_CHECK_MARKER,
        f"""
# {DOCS_CHECK_MARKER}: Reject hardcoded HOME paths
{PRECOMMIT_CHECK}
""",
    )

    hook_file.chmod(hook_file.stat().st_mode | 0o111)
    if changed:
        print("telec init: git pre-commit hook installed.")
    else:
        print("telec init: git hook already configured.")


def _append_block_if_missing(hook_file: Path, marker: str, block: str) -> bool:
    """Append a hook block only when marker is not already present."""
    existing = hook_file.read_text(encoding="utf-8") if hook_file.exists() else ""
    if marker in existing:
        return False

    with open(hook_file, "a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(block)
    return True


def _ensure_precommit_entrypoint_guard(precommit_hook_file: Path) -> None:
    """Inject stash prevention guard into pre-commit's generated git hook wrapper.

    This guard must run before pre-commit stashes unstaged files, so it cannot
    live only in `.pre-commit-config.yaml`. Migrates from the old overlap guard
    if present.
    """
    if not precommit_hook_file.exists():
        print("telec init: pre-commit entrypoint not found; run `pre-commit install`.")
        return

    content = precommit_hook_file.read_text(encoding="utf-8")
    anchor = '\nif [ -x "$INSTALL_PYTHON" ]; then'

    # Detect existing guard (current or old marker)
    existing_marker = None
    for marker in (STASH_PREVENTION_MARKER, _OLD_OVERLAP_MARKER):
        if marker in content:
            existing_marker = marker
            break

    if existing_marker:
        start = content.find(f"# {existing_marker}")
        if start == -1:
            return
        end = content.find(anchor, start)
        if end == -1:
            return
        patched = content[:start].rstrip("\n") + "\n\n" + STASH_PREVENTION_BLOCK + content[end:]
    else:
        idx = content.find(anchor)
        if idx == -1:
            patched = content.rstrip("\n") + "\n" + STASH_PREVENTION_BLOCK + "\n"
        else:
            patched = content[:idx] + "\n" + STASH_PREVENTION_BLOCK + content[idx:]

    precommit_hook_file.write_text(patched, encoding="utf-8")
    precommit_hook_file.chmod(precommit_hook_file.stat().st_mode | 0o111)
    print("telec init: pre-commit entrypoint guard installed.")
