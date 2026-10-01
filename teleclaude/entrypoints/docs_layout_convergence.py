"""Converge every registered repository to the documentation layout.

Composition root for ``teleclaude.docs_layout``: walks the project registry (or
the roots named on the command line), resolves an attributable commit party
before touching anything, and wires the sealed ``telec code commit`` and a
bounded fetch into each root's convergence. Prints one line per root and one
run line, and exits non-zero on any blocked, deferred, restored or conflicted
root. Contract: ``projects/teleclaude/spec/feature/context/documentation-layout-convergence``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Final
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.cli.session_auth import resolve_cli_identity
from teleclaude.commit_identity import CommitIdentityUnresolvable, resolve_commit_identity_from_caller
from teleclaude.docs_layout import (
    FAILING_OUTCOMES,
    LayoutCommitRefused,
    LayoutConvergenceOutcome,
    LayoutConvergenceResult,
    assess_root,
    converge_root,
)
from teleclaude.domains import valid_domains
from teleclaude.git import GitCommandError, Repo
from teleclaude.paths import REPO_ROOT
from teleclaude.project_manifest import load_registered_roots
from teleclaude.runtime.config import require_own_checkout
from teleclaude.snippet_validation import (
    RESERVED_SNIPPET_ID_PREFIXES,
    UndeclaredProjectSlugError,
    read_declared_project_slug,
)

logger = get_logger(__name__)

_COMMIT_MESSAGE: Final = "docs(layout): converge to docs/local, agents/local and qualified identities"
_TELEC_EXECUTABLE: Final = "telec"
_BIN_DIRNAME: Final = "bin"
_TELEC_CODE_COMMIT_ARGS: Final = ("code", "commit")
_TELEC_APPROVED_FLAG: Final = "--approved"
_TELEC_ONLY_FLAG: Final = "--only"
_TELEC_INVOCATION_CWD: Final = "TELEC_INVOCATION_CWD"
_PROCESS_CWD: Final = "PWD"
_WORKTREE_DIRECTORY: Final = "trees"
_INTEGRATION_WORKTREE: Final = "_integration"
_FETCH_TIMEOUT_SECONDS: Final = 30
_FETCH_QUIET: Final = "--quiet"
_GIT_TERMINAL_PROMPT: Final = "GIT_TERMINAL_PROMPT"
_GIT_TERMINAL_PROMPT_OFF: Final = "0"
_RERUN_COMMAND: Final = "uv run --directory {repo_root} python -m teleclaude.entrypoints.docs_layout_convergence"

_ROOT_LINE: Final = "docs-layout-convergence: {root} {outcome}"
_DETAIL_LINE: Final = "  {label}: {value}"
_RUN_LINE: Final = "docs-layout-convergence run: {outcome} roots={count} run_id={run_id}"
_REGISTRY_FAILED_LINE: Final = "docs-layout-convergence run: failed (project registry unreadable)"
_LABEL_BLOCKING: Final = "blocking"
_LABEL_COMMIT: Final = "commit"
_LABEL_MENTION: Final = "published mention (owner decides)"
_LABEL_WORKTREE: Final = "linked worktree"
_LABEL_RESIDUE: Final = "removed residue"
_LABEL_RERUN: Final = "re-run with an agent session or terminal login"
_RUN_OK: Final = "ok"
_RUN_FAILED: Final = "failed"
_LOG_RUN_EVENT: Final = "docs_layout_convergence_run"
_LOG_REGISTRY_FAILED_EVENT: Final = "docs_layout_convergence_registry_unreadable"
_LOG_ROOT_FAILED_EVENT: Final = "docs_layout_convergence_root_failed"
_PARSER_DESCRIPTION: Final = "Converge repositories to the docs/local documentation layout."
_ROOTS_ARGUMENT: Final = "roots"
_ROOTS_NARGS: Final = "*"
_ROOTS_HELP: Final = "Converge only these roots instead of the project registry."


def _telec_executable() -> Path:
    executable = REPO_ROOT / _BIN_DIRNAME / _TELEC_EXECUTABLE
    if REPO_ROOT.parent.name == _WORKTREE_DIRECTORY and REPO_ROOT.name != _INTEGRATION_WORKTREE:
        installed = shutil.which(_TELEC_EXECUTABLE)
        if installed is not None:
            executable = Path(installed)
    return executable


def sealed_committer(root: Path, paths: Sequence[str]) -> None:
    """Commit exactly ``paths`` in ``root`` through the sealed ``telec code commit``."""
    executable = _telec_executable()
    if not executable.is_file():
        raise LayoutCommitRefused(str(executable))
    working_root = root.resolve()
    environment = os.environ.copy()  # fmt: skip  # guard: direct-env-read - allowed: host environment forwarded to canonical CLI
    environment[_TELEC_INVOCATION_CWD] = str(working_root)
    environment[_PROCESS_CWD] = str(working_root)
    arguments = [
        str(executable),
        *_TELEC_CODE_COMMIT_ARGS,
        _COMMIT_MESSAGE,
        _TELEC_APPROVED_FLAG,
        _TELEC_ONLY_FLAG,
        *paths,
    ]
    # The sealed CLI is the only commit API that adds required author, session, and human-involvement metadata.
    try:
        subprocess.run(arguments, cwd=working_root, env=environment, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise LayoutCommitRefused(str(working_root)) from exc


def bounded_fetcher(repository: Repo) -> bool:
    """Fetch the current branch's upstream remote within a bounded time; report success."""
    try:
        tracking = repository.active_branch.tracking_branch()
    except TypeError:
        return False
    if tracking is None:
        return False
    try:
        with repository.git.custom_environment(**{_GIT_TERMINAL_PROMPT: _GIT_TERMINAL_PROMPT_OFF}):
            repository.git.fetch(_FETCH_QUIET, tracking.remote_name, kill_after_timeout=_FETCH_TIMEOUT_SECONDS)
    except GitCommandError:
        return False
    return True


def _has_attributable_party() -> bool:
    try:
        resolve_commit_identity_from_caller(resolve_cli_identity())
    except CommitIdentityUnresolvable:
        return False
    return True


def _registered_slugs(roots: Sequence[Path]) -> tuple[str, ...]:
    """Declared slugs of present registered roots that cannot be mistaken for a domain."""
    excluded = valid_domains() | RESERVED_SNIPPET_ID_PREFIXES
    slugs: set[str] = set()
    for root in roots:
        try:
            slug = read_declared_project_slug(root)
        except (UndeclaredProjectSlugError, ValueError):
            continue
        if slug not in excluded:
            slugs.add(slug)
    return tuple(sorted(slugs))


def _print_result(result: LayoutConvergenceResult) -> None:
    print(_ROOT_LINE.format(root=result.root, outcome=result.outcome.value))
    if result.commit is not None:
        print(_DETAIL_LINE.format(label=_LABEL_COMMIT, value=result.commit))
    for path in result.blocking_paths:
        print(_DETAIL_LINE.format(label=_LABEL_BLOCKING, value=path))
    for mention in result.published_mentions:
        print(_DETAIL_LINE.format(label=_LABEL_MENTION, value=mention))
    for worktree in result.worktrees:
        print(_DETAIL_LINE.format(label=_LABEL_WORKTREE, value=worktree))
    for path in result.removed_residue:
        print(_DETAIL_LINE.format(label=_LABEL_RESIDUE, value=path))
    if result.outcome is LayoutConvergenceOutcome.DEFERRED_NO_IDENTITY:
        print(_DETAIL_LINE.format(label=_LABEL_RERUN, value=_RERUN_COMMAND.format(repo_root=REPO_ROOT)))


def _converge_one(root: Path, *, attributable: bool, registered_slugs: Sequence[str]) -> LayoutConvergenceResult:
    require_own_checkout(root)
    try:
        return _converge_checked(root, attributable=attributable, registered_slugs=registered_slugs)
    except (GitCommandError, OSError):
        logger.exception(_LOG_ROOT_FAILED_EVENT, project_root=str(root))
        return LayoutConvergenceResult(root=root, outcome=LayoutConvergenceOutcome.FAILED)


def _converge_checked(root: Path, *, attributable: bool, registered_slugs: Sequence[str]) -> LayoutConvergenceResult:
    if attributable:
        return converge_root(
            root, registered_slugs=registered_slugs, committer=sealed_committer, fetcher=bounded_fetcher
        )
    terminal = assess_root(root, registered_slugs=registered_slugs, fetcher=bounded_fetcher)
    if terminal is not None:
        return terminal
    return LayoutConvergenceResult(root=root, outcome=LayoutConvergenceOutcome.DEFERRED_NO_IDENTITY)


def run(roots: Sequence[Path], present: Sequence[bool], *, slug_roots: Sequence[Path]) -> int:
    """Converge ``roots`` and print the report; return the process exit code."""
    run_id = uuid4().hex
    attributable = _has_attributable_party()
    registered_slugs = _registered_slugs(slug_roots)
    results: list[LayoutConvergenceResult] = []
    for root, is_present in zip(roots, present, strict=True):
        if not is_present:
            result = LayoutConvergenceResult(root=root, outcome=LayoutConvergenceOutcome.UNAVAILABLE)
        else:
            result = _converge_one(root, attributable=attributable, registered_slugs=registered_slugs)
        _print_result(result)
        results.append(result)
    failed = any(result.outcome in FAILING_OUTCOMES for result in results)
    outcome = _RUN_FAILED if failed else _RUN_OK
    logger.info(_LOG_RUN_EVENT, run_id=run_id, outcome=outcome, root_count=len(results), attributable=attributable)
    print(_RUN_LINE.format(outcome=outcome, count=len(results), run_id=run_id))
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Converge the registered roots, or only the roots named as arguments."""
    parser = argparse.ArgumentParser(description=_PARSER_DESCRIPTION)
    parser.add_argument(_ROOTS_ARGUMENT, nargs=_ROOTS_NARGS, type=Path, help=_ROOTS_HELP)
    arguments = parser.parse_args(argv)
    try:
        registered = load_registered_roots(strict=True)
    except RuntimeError:
        logger.exception(_LOG_REGISTRY_FAILED_EVENT)
        print(_REGISTRY_FAILED_LINE)
        return 1
    slug_roots = [entry.path for entry in registered if entry.is_present]
    if arguments.roots:
        roots = [root.expanduser().resolve() for root in arguments.roots]
        return run(roots, [root.is_dir() for root in roots], slug_roots=slug_roots)
    return run(
        [entry.path for entry in registered],
        [entry.is_present for entry in registered],
        slug_roots=slug_roots,
    )


if __name__ == "__main__":
    raise SystemExit(main())
