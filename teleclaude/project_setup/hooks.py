"""Pre-commit hook installation for TeleClaude docs check."""

from pathlib import Path

# Marker strings used for idempotent hook block insertion.
DOCS_CHECK_MARKER = "teleclaude-docs-check"
OVERLAP_GUARD_MARKER = "teleclaude-overlap-guard"

# Guard that blocks commits only when staged files also have unstaged edits.
# This avoids pre-commit stash/restore hazards while still allowing dirty trees.
OVERLAP_GUARD_BLOCK = f"""
# {OVERLAP_GUARD_MARKER}: block staged/unstaged overlap to keep commits safe
_teleclaude_staged="$(git diff --cached --name-only --diff-filter=ACM)"
if [ -n "$_teleclaude_staged" ]; then
  _teleclaude_overlap="$(comm -12 \
    <(printf '%s\\n' "$_teleclaude_staged" | sed '/^$/d' | sort -u) \
    <(git diff --name-only --diff-filter=ACM | sed '/^$/d' | sort -u))"
  if [ -n "$_teleclaude_overlap" ]; then
    echo "ERROR: controlled commit required."
    echo "The following files are both staged and unstaged:"
    printf '%s\\n' "$_teleclaude_overlap"
    echo "Stage cleanly (or commit in two steps) and retry."
    exit 1
  fi
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
    changed |= _append_block_if_missing(hook_file, OVERLAP_GUARD_MARKER, OVERLAP_GUARD_BLOCK)
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
    changed |= _append_block_if_missing(hook_file, OVERLAP_GUARD_MARKER, OVERLAP_GUARD_BLOCK)
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
    """Inject overlap guard into pre-commit's generated git hook wrapper.

    This guard must run before pre-commit stashes unstaged files, so it cannot
    live only in `.pre-commit-config.yaml`.
    """
    if not precommit_hook_file.exists():
        print("telec init: pre-commit entrypoint not found; run `pre-commit install`.")
        return

    content = precommit_hook_file.read_text(encoding="utf-8")
    anchor = '\nif [ -x "$INSTALL_PYTHON" ]; then'
    if OVERLAP_GUARD_MARKER in content:
        start = content.find(f"# {OVERLAP_GUARD_MARKER}")
        if start == -1:
            return
        end = content.find(anchor, start)
        if end == -1:
            return
        patched = content[:start].rstrip("\n") + "\n\n" + OVERLAP_GUARD_BLOCK + content[end:]
    else:
        idx = content.find(anchor)
        if idx == -1:
            # Fallback: append guard when hook format is unexpected.
            patched = content.rstrip("\n") + "\n" + OVERLAP_GUARD_BLOCK + "\n"
        else:
            patched = content[:idx] + "\n" + OVERLAP_GUARD_BLOCK + content[idx:]

    precommit_hook_file.write_text(patched, encoding="utf-8")
    precommit_hook_file.chmod(precommit_hook_file.stat().st_mode | 0o111)
    print("telec init: pre-commit entrypoint guard installed.")
