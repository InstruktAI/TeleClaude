"""Git smudge/clean filter setup for tilde expansion.

The ``teleclaude-docs`` filter expands ``@~/.teleclaude`` to ``@$HOME/.teleclaude``
on checkout (smudge) and contracts it back on commit (clean). The filter *driver*
lives in ``.git/config`` — which is per-clone and never committed — so a fresh
clone has the ``.gitattributes`` rule but no driver, and smudge silently no-ops.

``ensure_git_filters`` is the self-healing entry point: when the docs capability is
enabled after sync validation, it (re)installs the driver and force re-smudges any
already-checked-out files that are still unexpanded.
"""

import re
import stat
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.git import GitCommandError, Repo

logger = get_logger(__name__)

# The portable token written to disk by the clean filter (and present in any
# checkout where smudge never ran). Detecting it identifies stale files.
PRE_SMUDGE_TOKEN = "@~/.teleclaude"

# The portable doc-prose form of a home reference. The clean filter only ever
# substitutes the home root for this token, so collapsing an absolute home path
# back to it is the one legitimate filter effect — the basis for telling filter
# residue (safe to reset) apart from a genuine edit (must be preserved).
_PORTABLE_HOME = "~/.teleclaude"

# The filter only ever applies under docs/ (see .gitattributes and
# gitattributes.FILTER_PATTERNS). Scoping the working-tree scan here keeps it
# fast — it skips the rest of the tracked tree — and states the intent plainly.
_FILTER_SCOPE = "docs"
_FILTER_SECTION = "filter.teleclaude-docs"
_REMOVE_SECTION_ARGUMENT = "--remove-section"
_FILTER_REMOVED_MESSAGE = "git_filters: docs filter driver removed."
_FILTER_SECTION_ABSENT_MESSAGE = "no such section"
_CONFIG_VALUE_ABSENT_STATUS = 1


class GitFilterDisposition(StrEnum):
    """Terminal disposition for one repository's docs filter driver."""

    CONFIGURED = "configured"
    REMOVED = "removed"
    NOT_A_REPOSITORY = "not_a_repository"


def ensure_git_filters(project_root: Path, *, enabled: bool = True) -> GitFilterDisposition:
    """Converge the filter driver to the docs capability declaration.

    Idempotent and CI-safe. Installs the driver into ``.git/config`` and re-runs
    smudge on filtered files that are unmodified yet still hold the pre-smudge
    token. Locally modified files are left untouched to avoid clobbering edits.

    Args:
        project_root: Path to the project root directory.
        enabled: Whether the project's docs capability is enabled.
    """
    if not (project_root / ".git").exists():
        print("git_filters: not a git repository, skipping filter setup.")
        return GitFilterDisposition.NOT_A_REPOSITORY

    repo = Repo(project_root)
    if not enabled:
        _remove_filter_driver(repo)
        return GitFilterDisposition.REMOVED
    _configure_filter_driver(repo)
    reconciled = _reconcile_filter_residue(repo, project_root)
    if reconciled:
        print(f"git_filters: reconciled {reconciled} file(s) from a prior filter pattern.")
    restored = _force_resmudge(repo, project_root)
    if restored:
        print(f"git_filters: re-smudged {restored} file(s) to absolute paths.")
    elif not reconciled:
        print("git_filters: filter driver configured; working tree already smudged.")
    return GitFilterDisposition.CONFIGURED


def _configure_filter_driver(repo: Repo) -> None:
    """Install the teleclaude-docs filter driver into the repo's git config."""
    home = str(Path.home())
    smudge_cmd = f'sed "s|@~/.teleclaude|@{home}/.teleclaude|g"'
    clean_cmd = f'sed "s|@{home}/.teleclaude|@~/.teleclaude|g"'

    _run_git_config(repo, "filter.teleclaude-docs.smudge", smudge_cmd)
    _run_git_config(repo, "filter.teleclaude-docs.clean", clean_cmd)
    _run_git_config(repo, "filter.teleclaude-docs.required", "true")


def _remove_filter_driver(repo: Repo) -> None:
    """Remove only TeleClaude's untracked docs filter configuration."""
    try:
        repo.git.config(_REMOVE_SECTION_ARGUMENT, _FILTER_SECTION)
    except GitCommandError as exc:
        if _FILTER_SECTION_ABSENT_MESSAGE in str(exc).lower():
            return
        logger.warning("git_filters: unable to remove docs filter driver", exc_info=True)
        raise
    print(_FILTER_REMOVED_MESSAGE)


def _force_resmudge(repo: Repo, project_root: Path) -> int:
    """Re-run smudge on filtered files that are clean but still unexpanded.

    Returns the number of files restored. Candidates are found by grepping the
    working tree for the pre-smudge token (cheap, narrows to a handful), then
    confirmed against the resolved ``filter`` attribute so files that legitimately
    keep the token (``-filter`` overrides) are left alone. Locally modified files
    are skipped to avoid clobbering edits. Deleting and re-checking out the rest
    re-runs the smudge filter.

    A failed checkout (for example Git refusing an occupied ``index.lock``) leaves
    the candidates as they were: every candidate the checkout did not recreate is
    written back with its prior bytes and file mode, and the checkout error then
    propagates unchanged. The next convergence selects the still-unexpanded files
    again.
    """
    token_files = _files_with_token(repo)
    if not token_files:
        return 0

    matched = _filter_matched(repo, token_files)
    stale = sorted(set(matched) - _modified_files(repo))
    if not stale:
        return 0

    preimages: dict[str, tuple[bytes, int]] = {}
    for relative_path in stale:
        target = project_root / relative_path
        preimages[relative_path] = (target.read_bytes(), stat.S_IMODE(target.stat().st_mode))
    for relative_path in stale:
        (project_root / relative_path).unlink()
    try:
        repo.git.checkout("--", *stale)
    except GitCommandError:
        _restore_preimages(project_root, preimages)
        raise
    return len(stale)


def _restore_preimages(project_root: Path, preimages: dict[str, tuple[bytes, int]]) -> None:
    """Write back each removed file the failed checkout did not recreate."""
    for relative_path, (content, mode) in preimages.items():
        target = project_root / relative_path
        if target.exists():
            continue
        target.write_bytes(content)
        target.chmod(mode)


def _reconcile_filter_residue(repo: Repo, project_root: Path) -> int:
    """Reset filtered files left in a prior filter pattern's bare-absolute home form.

    A working tree last smudged under the historical *bare* driver carries
    bare-absolute ``<home>/.teleclaude`` paths that the current *anchored* clean
    filter cannot contract, so git reports them modified — surfacing as unrelated
    docs mutations and as hardcoded-HOME guardrail offenses. This converges those
    files to the committed canonical form via the same delete + checkout primitive
    as the token lane, but keyed on residue the token lane is blind to.

    The genuine-edit guard resets a file only when its sole divergence from the
    committed blob is home-path representation: ``normalize(working)`` must equal
    ``normalize(index_blob)`` after collapsing absolute home paths back to the
    portable token. A real content edit fails that equality and is left untouched.
    On an already-consistent tree there are no candidates, so this is a no-op.

    Returns the number of files reset.
    """
    home = str(Path.home())
    candidates = _filter_matched(repo, _files_with_home_path(repo, home))
    residue = re.compile(r"(?<!@)" + re.escape(home) + r"/\.teleclaude")
    stale: list[str] = []
    for relative_path in candidates:
        working = (project_root / relative_path).read_text(encoding="utf-8")
        if not residue.search(working):
            continue
        index_blob = _index_blob(repo, relative_path)
        if _normalize_home(working, home) == _normalize_home(index_blob, home):
            stale.append(relative_path)

    ordered = sorted(set(stale))
    if not ordered:
        return 0
    for relative_path in ordered:
        (project_root / relative_path).unlink()
    repo.git.checkout("--", *ordered)
    return len(ordered)


def _files_with_home_path(repo: Repo, home: str) -> list[str]:
    """Return tracked docs files whose working tree holds an absolute home path.

    Fixed-string grep keeps the scan cheap; it over-matches ``@``-prefixed smudge
    output, which the caller's residue check then filters out. NUL-framed like the
    other working-tree scans, robust to any character in a tracked path.
    """
    try:
        listed: str = repo.git.grep("-l", "-z", "-F", f"{home}/.teleclaude", "--", _FILTER_SCOPE)
    except GitCommandError as exc:
        if exc.status == 1:  # git grep exits 1 when nothing matches
            return []
        raise
    return [path for path in listed.split("\0") if path]


def _index_blob(repo: Repo, relative_path: str) -> str:
    """Return the committed (cleaned) blob for a path from the index, bytes-exact.

    ``strip_newline_in_stdout=False`` preserves the trailing newline so the
    residue guard compares working and index content without a spurious newline
    divergence.
    """
    blob: str = repo.git.show(f":{relative_path}", strip_newline_in_stdout=False)
    return blob


def _normalize_home(text: str, home: str) -> str:
    """Collapse absolute home references to the portable token for residue comparison."""
    return text.replace(f"{home}/.teleclaude", _PORTABLE_HOME)


def _files_with_token(repo: Repo) -> list[str]:
    """Return tracked docs files whose working-tree content holds the pre-smudge token.

    NUL-framed (``-z``) like the check-attr scan below, so paths are split on NUL
    rather than newlines — robust to any character in a tracked path.
    """
    try:
        listed: str = repo.git.grep("-l", "-z", "-F", PRE_SMUDGE_TOKEN, "--", _FILTER_SCOPE)
    except GitCommandError as exc:
        if exc.status == 1:  # git grep exits 1 when nothing matches
            return []
        raise
    return [path for path in listed.split("\0") if path]


def _filter_matched(repo: Repo, paths: list[str]) -> list[str]:
    """Return the subset of ``paths`` whose resolved ``filter`` attribute is teleclaude-docs."""
    if not paths:
        return []

    raw = repo.git.check_attr("filter", "-z", "--", *paths)
    fields = raw.split("\0")
    matched: list[str] = []
    for index in range(0, len(fields) - 2, 3):
        path, _attr, value = fields[index], fields[index + 1], fields[index + 2]
        if value == "teleclaude-docs":
            matched.append(path)
    return matched


def _modified_files(repo: Repo) -> set[str]:
    """Return tracked files with staged or unstaged local modifications."""
    unstaged = repo.git.diff("--name-only").splitlines()
    staged = repo.git.diff("--cached", "--name-only").splitlines()
    return set(unstaged) | set(staged)


def _run_git_config(repo: Repo, key: str, value: str) -> None:
    """Converge a local config key without rewriting an identical value."""
    try:
        existing = repo.git.config("--local", "--get-all", key)
    except GitCommandError as error:
        if error.status != _CONFIG_VALUE_ABSENT_STATUS:
            raise
        existing = ""
    if tuple(existing.splitlines()) == (value,):
        return
    repo.git.config("--local", "--replace-all", key, value)
