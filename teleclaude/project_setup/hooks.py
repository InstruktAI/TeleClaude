"""Pre-commit hook installation for TeleClaude docs check."""

from pathlib import Path
from typing import cast

import yaml

# Marker strings used for idempotent hook block insertion.
DOCS_CHECK_MARKER = "teleclaude-docs-check"
STASH_PREVENTION_MARKER = "teleclaude-stash-prevention"
RESTAGE_MARKER = "teleclaude-format-restage"
_OLD_OVERLAP_MARKER = "teleclaude-overlap-guard"

# Guard that blocks commits when ANY unstaged changes to tracked files exist.
# WHY: pre-commit's staged_files_only.py saves unstaged changes as a patch, runs
# `git checkout -- .` (nukes working tree), runs hooks, then `git apply` to restore.
# When apply fails (deleted files, conflicts with hook formatting), unstaged changes
# are permanently lost. By requiring a clean working tree, _unstaged_changes_cleared()
# always takes the safe retcode==0 path (no patch, no checkout, no data loss).
STASH_PREVENTION_BLOCK = f"""
# {STASH_PREVENTION_MARKER}: block commits with partially staged files
_staged="$(git diff --cached --name-only | sort)"
_unstaged="$(git diff --name-only | sort)"
if [ -n "$_staged" ] && [ -n "$_unstaged" ]; then
  _overlap="$(comm -12 <(printf '%s\\n' $_staged) <(printf '%s\\n' $_unstaged))"
  if [ -n "$_overlap" ]; then
    echo "ERROR: partially staged files detected."
    echo "Pre-commit stash/restore would corrupt these files."
    echo ""
    echo "Affected files (staged AND unstaged):"
    printf '  %s\\n' $_overlap
    echo ""
    echo "Stage remaining hunks (git add -p) or discard them (git checkout -- <file>)."
    exit 1
  fi
fi
"""

# Captures staged files before hooks, runs pre-commit as a regular call (not exec), then
# restages formatter-modified files and retries pre-commit once so the commit completes in
# one go. Pre-commit returns non-zero when a hook modifies files, so restaging must happen
# on the failure path — not only on success.
RESTAGE_BLOCK = f"""\
# {RESTAGE_MARKER}: capture staged files before hooks run
_pre_staged="$(git diff --cached --name-only --diff-filter=ACM)"

_teleclaude_run_precommit() {{
    if [ -x "$INSTALL_PYTHON" ]; then
        "$INSTALL_PYTHON" -mpre_commit "${{ARGS[@]}}"
        return $?
    elif command -v pre-commit > /dev/null; then
        pre-commit "${{ARGS[@]}}"
        return $?
    fi
    echo '`pre-commit` not found.  Did you forget to activate your virtualenv?' 1>&2
    return 127
}}

_teleclaude_run_precommit
_rc=$?

# Collect previously-staged files that formatters modified (now unstaged).
_modified=""
if [ -n "$_pre_staged" ]; then
    for _f in $_pre_staged; do
        if [ -f "$_f" ] && ! git diff --quiet -- "$_f"; then
            _modified="$_modified $_f"
        fi
    done
fi

# Restage formatter edits, then retry pre-commit once if it had failed because of them.
if [ -n "$_modified" ]; then
    if ! git add -- $_modified; then
        echo "ERROR: failed to restage formatted files — aborting commit." >&2
        exit 1
    fi
    if [ $_rc -ne 0 ]; then
        echo "Restaged formatter-modified files; re-running pre-commit..."
        _teleclaude_run_precommit
        _rc=$?
    fi
fi

exit $_rc
"""

# Check command that detects hardcoded HOME paths in staged .md files
PRECOMMIT_CHECK = (
    "git diff --cached --name-only --diff-filter=ACM | "
    "grep '\\.md$' | "
    'xargs -r grep -l "@/Users/\\|@/home/" && '
    "echo \"ERROR: Hardcoded HOME paths found in docs. Run 'telec projects init' to set up filters.\" && "
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
        print("telec projects init: no git hooks directory found, skipping hook installation.")


def _add_precommit_framework_hook(config_path: Path) -> None:
    """Add hook to pre-commit framework config."""
    content = config_path.read_text(encoding="utf-8")

    if DOCS_CHECK_MARKER in content:
        print("telec projects init: pre-commit hook already configured.")
        return

    try:
        loaded_config: object = yaml.safe_load(content)
    except yaml.YAMLError:
        print("telec projects init: failed to parse .pre-commit-config.yaml, skipping hook.")
        return
    config_obj = loaded_config if loaded_config is not None else {}

    if not isinstance(config_obj, dict):
        print("telec projects init: unexpected .pre-commit-config.yaml structure, skipping hook.")
        return

    config = cast(dict[str, object], config_obj)  # guard: loose-dict - JSON config from external tool

    repos_obj = config.get("repos")
    if repos_obj is None:
        repos: list[object] = []
        config["repos"] = repos
    elif isinstance(repos_obj, list):
        repos = repos_obj
    else:
        print("telec projects init: unexpected repos structure in .pre-commit-config.yaml, skipping hook.")
        return

    teleclaude_hook: dict[str, object] = {  # guard: loose-dict - JSON config construction for external tool
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
    repos.append(teleclaude_hook)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)
    print("telec projects init: pre-commit hook added to .pre-commit-config.yaml.")


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
        print("telec projects init: husky pre-commit hook updated.")
    else:
        print("telec projects init: husky hook already configured.")


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
        print("telec projects init: git pre-commit hook installed.")
    else:
        print("telec projects init: git hook already configured.")


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
    """Inject stash prevention and format-restage blocks into pre-commit's generated hook wrapper.

    Replaces any pre-existing TeleClaude blocks (stash prevention, the old overlap
    guard, or a prior restage block) with a fresh pair so updates land cleanly on
    re-run. On a fresh install the ``exec`` tail is removed so the restage block
    owns the pre-commit invocation.
    """
    if not precommit_hook_file.exists():
        print("telec projects init: pre-commit entrypoint not found; run `pre-commit install`.")
        return

    content = precommit_hook_file.read_text(encoding="utf-8")

    marker_comments = (
        "# teleclaude-session-scoped-staging",  # legacy marker for upgrade cleanup
        f"# {STASH_PREVENTION_MARKER}",
        f"# {_OLD_OVERLAP_MARKER}",
        f"# {RESTAGE_MARKER}",
    )
    teleclaude_start: int | None = None
    for marker in marker_comments:
        idx = content.find(marker)
        if idx != -1 and (teleclaude_start is None or idx < teleclaude_start):
            teleclaude_start = idx

    if teleclaude_start is not None:
        prefix = content[:teleclaude_start].rstrip("\n")
    else:
        exec_anchor = '\nif [ -x "$INSTALL_PYTHON" ]; then'
        idx = content.find(exec_anchor)
        prefix = (content[:idx] if idx != -1 else content).rstrip("\n")

    content = prefix + "\n" + STASH_PREVENTION_BLOCK + "\n" + RESTAGE_BLOCK

    precommit_hook_file.write_text(content, encoding="utf-8")
    precommit_hook_file.chmod(precommit_hook_file.stat().st_mode | 0o111)
    print("telec projects init: pre-commit entrypoint guard installed.")
