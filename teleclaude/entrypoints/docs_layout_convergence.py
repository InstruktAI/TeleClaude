"""Converge every registered repository to the documentation layout.

Composition root for ``teleclaude.docs_layout``: walks the project registry (or
the roots named on the command line), resolves an attributable commit party
before touching anything, and wires the sealed ``telec repo commit`` and a
bounded fetch into each root's convergence, under a per-repository lock. Prints
one line per root and one run line, and exits ``0`` when every root is settled,
a dedicated status when some root is blocked or deferred and none failed, and
``1`` when any root failed, was restored after a refused commit or is in restore
conflict. Contract: ``local/projects/teleclaude/spec/feature/context/documentation-layout-convergence``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from stat import S_ISREG
from typing import Final
from uuid import uuid4

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.cli.session_auth import resolve_cli_identity
from teleclaude.commit_identity import CommitIdentityUnresolvable, resolve_commit_identity_from_caller
from teleclaude.constants import SYSTEM_OPERATOR_PRINCIPAL
from teleclaude.docs_layout import (
    LayoutCommitRefused,
    LayoutConvergenceOutcome,
    LayoutConvergenceResult,
    LayoutResultClass,
    assess_root,
    converge_root,
    registered_project_slugs,
    repository_convergence_lock,
    run_class,
)
from teleclaude.git import GitCommandError, Repo
from teleclaude.paths import REPO_ROOT, TELECLAUDE_HOME
from teleclaude.project_manifest import load_registered_roots
from teleclaude.runtime.config import ForeignRepositoryWriteRefusedError, require_own_checkout
from teleclaude.snippet_roots import iter_tier_snippet_roots
from teleclaude.snippet_scope import HOME_IDENTITY_PREFIXES
from teleclaude.sync import HomePublicationOutcome, PublicationMode, publish_homes

logger = get_logger(__name__)

_COMMIT_MESSAGE: Final = "docs(layout): converge to docs/local, agents/local and qualified identities"
_TELEC_EXECUTABLE: Final = "telec"
_BIN_DIRNAME: Final = "bin"
_TELEC_REPO_COMMIT_ARGS: Final = ("repo", "commit")
_TELEC_APPROVED_FLAG: Final = "--approved"
_TELEC_ONLY_FLAG: Final = "--only"
_TELEC_INVOCATION_CWD: Final = "TELEC_INVOCATION_CWD"
_PROCESS_CWD: Final = "PWD"
_WORKTREE_DIRECTORY: Final = "trees"
_INTEGRATION_WORKTREE: Final = "_integration"
_FETCH_TIMEOUT_SECONDS: Final = 30
_FETCH_QUIET: Final = "--quiet"
_GIT_TERMINAL_PROMPT: Final = "GIT_TERMINAL_PROMPT"
_ROOT_RELATIVE_PATH: Final = Path(".")
_HOME_FIELD: Final = "home"
_OUTCOME_FIELD: Final = "outcome"
_ERROR_FIELD: Final = "error"
_GIT_TERMINAL_PROMPT_OFF: Final = "0"
_RERUN_COMMAND: Final = "uv run --directory {repo_root} python -m teleclaude.entrypoints.docs_layout_convergence"

_ROOT_LINE: Final = "docs-layout-convergence: {root} {outcome}"
_WAITING_LINE: Final = "docs-layout-convergence: {root} waiting for another convergence of this repository"
_DETAIL_LINE: Final = "  {label}: {value}"
_RUN_LINE: Final = "docs-layout-convergence run: {outcome} roots={count} run_id={run_id}"
_REGISTRY_FAILED_LINE: Final = "docs-layout-convergence run: failed (project registry unreadable)"
_LABEL_BLOCKING: Final = "blocking"
_LABEL_COMMIT: Final = "commit"
_LABEL_MENTION: Final = "published mention (owner decides)"
_LABEL_WORKTREE: Final = "linked worktree"
_LABEL_RESIDUE: Final = "removed residue"
_LABEL_CATALOG_REFRESH: Final = "local catalog refresh"
_CATALOG_REFRESHED: Final = "refreshed"
_CATALOG_REFRESH_FAILED: Final = "failed"
_LOCAL_CATALOG_INDEX: Final = Path("docs/local/index.yaml")
_LOCAL_CATALOG_SNIPPETS_KEY: Final = "snippets"
_LOCAL_CATALOG_ID_KEY: Final = "id"
_IDENTITY_SEPARATOR: Final = "/"
_UTF8: Final = "utf-8"
_LEGACY_HOME_IDENTITY_PREFIXES: Final = frozenset(HOME_IDENTITY_PREFIXES.values())
_LOCAL_CATALOG_INSPECTION_FAILED_EVENT: Final = "docs_layout_local_catalog_inspection_failed"
_LOCAL_CATALOG_REFRESH_FAILED_EVENT: Final = "docs_layout_local_catalog_refresh_failed"
_CATALOG_REFRESH_DETAIL_TEMPLATE: Final = "{name}={status}"
_CATALOG_REFRESH_SEPARATOR: Final = "; "
_PROJECT_CATALOG_NAME: Final = "project"
_PLATFORM_TIER_CATALOG_NAME: Final = "platform tiers"
_LABEL_RERUN: Final = "re-run with an agent session or terminal login"
#: How a run reports itself and exits, by its most severe root. The held status is
#: distinct from the failure status and from argparse's usage status; installation
#: reads these statuses (``bin/install.sh``), so they are one published contract.
_RUN_LABELS: Final[dict[LayoutResultClass, str]] = {
    LayoutResultClass.SETTLED: "ok",
    LayoutResultClass.HELD: "held",
    LayoutResultClass.FAILURE: "failed",
}
EXIT_STATUSES: Final[dict[LayoutResultClass, int]] = {
    LayoutResultClass.SETTLED: 0,
    LayoutResultClass.HELD: 3,
    LayoutResultClass.FAILURE: 1,
}
_LOG_RUN_EVENT: Final = "docs_layout_convergence_run"
_LOG_REGISTRY_FAILED_EVENT: Final = "docs_layout_convergence_registry_unreadable"
_LOG_ROOT_FAILED_EVENT: Final = "docs_layout_convergence_root_failed"
_LOG_WAITING_EVENT: Final = "docs_layout_convergence_waiting"
_PARSER_DESCRIPTION: Final = "Converge repositories to the docs/local documentation layout."
_ROOTS_ARGUMENT: Final = "roots"
_ROOTS_NARGS: Final = "*"
_ROOTS_HELP: Final = "Converge only these roots instead of the project registry."


def _local_catalog_has_unqualified_home_ids(root: Path, *, log_inspection_error: bool = True) -> bool:
    """Whether a local catalog needs refresh because it is stale or unreadable."""
    index_path = root / _LOCAL_CATALOG_INDEX
    try:
        index_stat = index_path.stat()
    except FileNotFoundError:
        return False
    except OSError:
        if log_inspection_error:
            logger.warning(_LOCAL_CATALOG_INSPECTION_FAILED_EVENT, path=str(index_path), entry_count=-1)
        return True
    if not S_ISREG(index_stat.st_mode):
        if log_inspection_error:
            logger.warning(_LOCAL_CATALOG_INSPECTION_FAILED_EVENT, path=str(index_path), entry_count=-1)
        return True
    try:
        payload = yaml.safe_load(index_path.read_text(encoding=_UTF8))
    except (OSError, yaml.YAMLError):
        if log_inspection_error:
            logger.warning(_LOCAL_CATALOG_INSPECTION_FAILED_EVENT, path=str(index_path), entry_count=-1)
        return True
    snippets = payload.get(_LOCAL_CATALOG_SNIPPETS_KEY) if isinstance(payload, dict) else None
    if not isinstance(snippets, list):
        if log_inspection_error:
            logger.warning(_LOCAL_CATALOG_INSPECTION_FAILED_EVENT, path=str(index_path), entry_count=-1)
        return True
    return any(
        isinstance(snippet_id, str) and snippet_id.split(_IDENTITY_SEPARATOR, 1)[0] in _LEGACY_HOME_IDENTITY_PREFIXES
        for entry in snippets
        if isinstance(entry, dict)
        for snippet_id in (entry.get(_LOCAL_CATALOG_ID_KEY),)
    )


def _platform_tier_catalogs_have_unqualified_ids(*, log_inspection_error: bool = True) -> bool:
    """Whether any platform person or company local catalog needs rebuilding."""
    return any(
        _local_catalog_has_unqualified_home_ids(tier_root, log_inspection_error=log_inspection_error)
        for tier_root, _kind in iter_tier_snippet_roots(TELECLAUDE_HOME)
    )


def _publish_catalog_refresh(publisher_root: Path, still_stale: Callable[[], bool]) -> bool:
    """Rebuild the root's committed homes, then verify its local catalog is current."""
    try:
        publication = publish_homes(publisher_root, PublicationMode.REBUILD, directory=_ROOT_RELATIVE_PATH)
    except (GitCommandError, OSError, ValueError):
        logger.exception(_LOCAL_CATALOG_REFRESH_FAILED_EVENT, project_root=str(publisher_root))
        return False
    non_published_homes = [
        {
            _HOME_FIELD: item.home.root.as_posix(),
            _OUTCOME_FIELD: item.outcome.value,
            _ERROR_FIELD: item.error,
        }
        for item in publication.homes
        if item.outcome in (HomePublicationOutcome.SKIPPED, HomePublicationOutcome.FAILED)
    ]
    if publication.exit_code:
        logger.error(
            _LOCAL_CATALOG_REFRESH_FAILED_EVENT,
            project_root=str(publisher_root),
            tip=publication.tip,
            non_published_homes=non_published_homes,
            error=publication.error,
        )
        return False
    try:
        stale = still_stale()
    except (OSError, ValueError) as exc:
        logger.exception(
            _LOCAL_CATALOG_REFRESH_FAILED_EVENT,
            project_root=str(publisher_root),
            tip=publication.tip,
            non_published_homes=non_published_homes,
            error=str(exc),
        )
        return False
    if stale:
        logger.error(
            _LOCAL_CATALOG_REFRESH_FAILED_EVENT,
            project_root=str(publisher_root),
            tip=publication.tip,
            non_published_homes=non_published_homes,
            stale=True,
        )
        return False
    return True


def _telec_executable() -> Path:
    executable = REPO_ROOT / _BIN_DIRNAME / _TELEC_EXECUTABLE
    if REPO_ROOT.parent.name == _WORKTREE_DIRECTORY and REPO_ROOT.name != _INTEGRATION_WORKTREE:
        installed = shutil.which(_TELEC_EXECUTABLE)
        if installed is not None:
            executable = Path(installed)
    return executable


def sealed_committer(root: Path, paths: Sequence[str]) -> None:
    """Commit exactly ``paths`` in ``root`` through the sealed ``telec repo commit``."""
    executable = _telec_executable()
    if not executable.is_file():
        raise LayoutCommitRefused(str(executable))
    working_root = root.resolve()
    environment = os.environ.copy()  # fmt: skip  # guard: direct-env-read - allowed: host environment forwarded to canonical CLI
    environment[_TELEC_INVOCATION_CWD] = str(working_root)
    environment[_PROCESS_CWD] = str(working_root)
    arguments = [
        str(executable),
        *_TELEC_REPO_COMMIT_ARGS,
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
    """Whether an agent session or a person resolved at a terminal runs this convergence.

    The computer's operator outside any session is not such a party: a run with
    neither defers its roots to a later attributable run.
    """
    identity = resolve_cli_identity()
    if identity.session_id is None and identity.principal == SYSTEM_OPERATOR_PRINCIPAL:
        return False
    try:
        resolve_commit_identity_from_caller(identity)
    except CommitIdentityUnresolvable:
        return False
    return True


def _print_result(result: LayoutConvergenceResult) -> None:
    print(_ROOT_LINE.format(root=result.root, outcome=result.outcome.value))
    if result.commit is not None:
        print(_DETAIL_LINE.format(label=_LABEL_COMMIT, value=result.commit))
    if result.catalog_refresh is not None:
        print(_DETAIL_LINE.format(label=_LABEL_CATALOG_REFRESH, value=result.catalog_refresh))
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


def _announce_waiting(root: Path) -> None:
    logger.info(_LOG_WAITING_EVENT, project_root=str(root))
    print(_WAITING_LINE.format(root=root), flush=True)


def _converge_one(root: Path, *, attributable: bool, registered_slugs: Sequence[str]) -> LayoutConvergenceResult:
    try:
        require_own_checkout(root)
    except ForeignRepositoryWriteRefusedError:
        return LayoutConvergenceResult(root=root, outcome=LayoutConvergenceOutcome.FOREIGN_CHECKOUT)
    try:
        with repository_convergence_lock(root, lambda: _announce_waiting(root)):
            return _converge_and_refresh(root, attributable=attributable, registered_slugs=registered_slugs)
    except (GitCommandError, OSError):
        logger.exception(_LOG_ROOT_FAILED_EVENT, project_root=str(root))
        return LayoutConvergenceResult(root=root, outcome=LayoutConvergenceOutcome.FAILED)


def _converge_and_refresh(
    root: Path, *, attributable: bool, registered_slugs: Sequence[str]
) -> LayoutConvergenceResult:
    result = _converge_checked(root, attributable=attributable, registered_slugs=registered_slugs)
    if result.outcome not in (LayoutConvergenceOutcome.CURRENT, LayoutConvergenceOutcome.MIGRATED_COMMITTED):
        return result
    refresh_details: list[str] = []
    refresh_failed = False
    if _local_catalog_has_unqualified_home_ids(root):
        project_refreshed = _publish_catalog_refresh(
            root, lambda: _local_catalog_has_unqualified_home_ids(root, log_inspection_error=False)
        )
        project_status = _CATALOG_REFRESHED if project_refreshed else _CATALOG_REFRESH_FAILED
        refresh_details.append(
            _CATALOG_REFRESH_DETAIL_TEMPLATE.format(name=_PROJECT_CATALOG_NAME, status=project_status)
        )
        refresh_failed = refresh_failed or not project_refreshed
    if root.resolve() == REPO_ROOT.resolve() and _platform_tier_catalogs_have_unqualified_ids():
        tiers_refreshed = _publish_catalog_refresh(
            TELECLAUDE_HOME,
            lambda: _platform_tier_catalogs_have_unqualified_ids(log_inspection_error=False),
        )
        tiers_status = _CATALOG_REFRESHED if tiers_refreshed else _CATALOG_REFRESH_FAILED
        refresh_details.append(
            _CATALOG_REFRESH_DETAIL_TEMPLATE.format(name=_PLATFORM_TIER_CATALOG_NAME, status=tiers_status)
        )
        refresh_failed = refresh_failed or not tiers_refreshed
    if not refresh_details:
        return result
    return replace(
        result,
        outcome=LayoutConvergenceOutcome.FAILED if refresh_failed else result.outcome,
        catalog_refresh=_CATALOG_REFRESH_SEPARATOR.join(refresh_details),
    )


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
    registered_slugs = registered_project_slugs(slug_roots)
    results: list[LayoutConvergenceResult] = []
    for root, is_present in zip(roots, present, strict=True):
        if not is_present:
            result = LayoutConvergenceResult(root=root, outcome=LayoutConvergenceOutcome.UNAVAILABLE)
        else:
            result = _converge_one(root, attributable=attributable, registered_slugs=registered_slugs)
        _print_result(result)
        results.append(result)
    run_result = run_class(results)
    outcome = _RUN_LABELS[run_result]
    logger.info(_LOG_RUN_EVENT, run_id=run_id, outcome=outcome, root_count=len(results), attributable=attributable)
    print(_RUN_LINE.format(outcome=outcome, count=len(results), run_id=run_id))
    return EXIT_STATUSES[run_result]


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
        return EXIT_STATUSES[LayoutResultClass.FAILURE]
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
