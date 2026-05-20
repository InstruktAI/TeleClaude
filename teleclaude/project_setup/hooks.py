"""Pre-commit entrypoint safety guards.

This module installs the *wrapper-level* guards that prevent commit corruption
during pre-commit runs (stash-prevention block, formatter-restage block). It
does **not** inject feature hooks like docs validation — those live as steps
inside ``telec code lint`` and are picked up via the shipped pre-commit
template's existing ``telec code lint`` entry.
"""

from pathlib import Path

# Marker strings used for idempotent hook block insertion.
STASH_PREVENTION_MARKER = "teleclaude-stash-prevention"
RESTAGE_MARKER = "teleclaude-format-restage"
_OLD_OVERLAP_MARKER = "teleclaude-overlap-guard"
_LEGACY_DOCS_CHECK_MARKER = "teleclaude-docs-check"

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
# The agent-facing wrapper blocks `git add`; this is git's own internal stash-restore
# step (not an agent action), so bypass via env -u TMUX (the wrapper's pass-through
# condition for non-tmux callers).
if [ -n "$_modified" ]; then
    if ! env -u TMUX git add -- $_modified; then
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


def ensure_precommit_safety_guards(project_root: Path) -> None:
    """Inject stash-prevention and format-restage blocks into the pre-commit wrapper.

    Operates on ``.git/hooks/pre-commit`` (the wrapper installed by
    ``pre-commit install``). If the wrapper does not exist, this is a no-op
    with a notice — the user must run ``pre-commit install`` first.
    """
    precommit_hook_file = project_root / ".git" / "hooks" / "pre-commit"

    if not precommit_hook_file.exists():
        print("telec projects init: pre-commit entrypoint not found; run `pre-commit install`.")
        return

    content = precommit_hook_file.read_text(encoding="utf-8")

    marker_comments = (
        "# teleclaude-session-scoped-staging",  # legacy marker for upgrade cleanup
        f"# {STASH_PREVENTION_MARKER}",
        f"# {_OLD_OVERLAP_MARKER}",
        f"# {RESTAGE_MARKER}",
        f"# {_LEGACY_DOCS_CHECK_MARKER}",  # cleanup of pre-migration docs-check injection
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
