"""Publish committed documentation and agent artifacts one home at a time."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.agent_artifacts import is_mother_project
from teleclaude.artifact_ownership import retired_pointer_candidate, retract_retired_pointers
from teleclaude.capabilities import PermissionSurface, resolve_capabilities, resolve_tier_permissions
from teleclaude.config.context_root import (
    TreeHome,
    group_paths_by_owning_home_tolerant,
    homes_at_or_beneath,
)
from teleclaude.config.schema import ConfigKind
from teleclaude.docs_index import build_all_indexes, build_tier_index, reroot_index_document
from teleclaude.docs_lock import DocsLeaseTimeoutError, DocsLockOperation, docs_lease
from teleclaude.docs_publishers import DocsPublisherResolutionError, git_common_root
from teleclaude.git import GitCommandError, Repo
from teleclaude.git_tree import TreeSource, list_tree_paths, materialize_tree
from teleclaude.install.distribution import (
    DistributionBuild,
    HomeMasterInflationError,
    committed_retired_outputs,
    distribute_committed,
)
from teleclaude.install.home_distribution import (
    HomeEntrypoint,
    TierHome,
    deployed_tier_identities,
    distribute_tier_homes,
    home_masters,
    inflate_home_entrypoint,
    inflate_home_entrypoints,
)
from teleclaude.paths import COMPANIES_ROOT, PEOPLE_DIR, TELECLAUDE_HOME, is_platform_home
from teleclaude.quality.gate import LintGateResult, run_home_guardrail_gate

logger = get_logger(__name__)

_GIT_MAIN_TIP_ARGS = ("--verify", "refs/heads/main^{commit}")
_GIT_IGNORED_UNTRACKED_ARGS = ("-z", "--others", "--ignored", "--exclude-standard", "--")
_GIT_PATH_SEPARATOR = "\0"
_COMMIT_ID_PATTERN = re.compile(r"[0-9a-f]{40,64}")
_STATE_DIRECTORY = ".teleclaude"
_PUBLICATION_DIRECTORY = "publication"
_HOME_GENERATIONS_FILENAME = "homes.yaml"
_PUBLISHED_GENERATION_FILENAME = "published_generation"
_UNFINISHED_PUBLICATION_FILENAME = "unfinished_publication"
_ENTRYPOINTS_GENERATION_FILENAME = "entrypoints_generation"
_PUBLICATION_NEXT_SUFFIX = ".publication-next"
_GIT_VERIFY_ERROR = "Could not resolve the canonical refs/heads/main commit."
_INVALID_HOME_STATE = "Per-home publication state is malformed: {path}"
_INVALID_HOME_STATE_ENTRY = "Per-home publication state has an invalid entry: {root}"
_HOME_SCOPE_REQUIRED = "Publication requires exactly one directory scope or changed-path scope."
_HOME_NOT_COMMITTED = "Home is not present in the committed main tip: {home}"
_UNSUPPORTED_HOME_POSITION = "Home kind {kind} at {root} is outside the supported home model."
_HOME_DECLARATION_FAILED = "Home declaration could not be read: {error}"
_HOME_BUILD_FAILED = "Home build failed: {error}"
_HOME_INSTALL_FAILED = "Home install failed: {error}"
_HOME_DIAGNOSTIC_FAILED = "Findings unavailable: {error}"
_HOME_DIAGNOSTIC_EVENT = "home_publication_skip_diagnosis"
_HOME_PUBLICATION_EVENT = "home_publication_outcome"
_HOME_PUBLICATION_RUN_EVENT = "home_publication_run"
_HOME_REFRESH_FAILED_EVENT = "home_entrypoint_refresh_failed"
_HOME_REFRESH_SKIPPED_EVENT = "home_entrypoint_refresh_skipped"
_NO_PUBLISHED_HOME_GENERATIONS = "no_published_home_generations"
_ROOT_RELATIVE_PATH = Path(".")
_ERROR_SEPARATOR = ", "
_UTF8 = "utf-8"
_EMPTY_STRING = ""
_BUILD_FAILURES = (
    DocsPublisherResolutionError,
    GitCommandError,
    HomeMasterInflationError,
    OSError,
    RuntimeError,
    subprocess.CalledProcessError,
    ValueError,
    yaml.YAMLError,
    SystemExit,
)


class PublicationMode(StrEnum):
    """The publication behavior selected by an entry point."""

    OWED = "owed"
    REBUILD = "rebuild"


class HomePublicationOutcome(StrEnum):
    """One home's terminal result for a publication run."""

    PUBLISHED = "published"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    FAILED = "failed"


class PublicationRunFailure(StrEnum):
    """A run-level refusal that happens before any home is built."""

    MAIN_TIP_UNAVAILABLE = "main_tip_unavailable"
    HOME_NOT_COMMITTED = "home_not_committed"
    RUN_FAILED = "run_failed"


class _HomeCategory(StrEnum):
    PROJECT = "project"
    GLOBAL = "global"
    TIER = "tier"


@dataclass(frozen=True)
class HomePublicationResult:
    """One home result, including optional build diagnosis."""

    home: TreeHome
    tip: str
    mode: PublicationMode
    outcome: HomePublicationOutcome
    error: str | None = None
    diagnostic: LintGateResult | None = None
    diagnostic_error: str | None = None


@dataclass(frozen=True)
class PublicationRun:
    """All home outcomes from one serialized publication run."""

    tip: str | None
    mode: PublicationMode
    homes: tuple[HomePublicationResult, ...]
    error: str | None = None
    failure: PublicationRunFailure | None = None

    @property
    def exit_code(self) -> int:
        """Return nonzero when the run or any home did not complete."""
        if self.error is not None:
            return 1
        return int(
            any(home.outcome in (HomePublicationOutcome.SKIPPED, HomePublicationOutcome.FAILED) for home in self.homes)
        )


@dataclass(frozen=True)
class _BuiltHome:
    home: TreeHome
    category: _HomeCategory
    tier: TierHome | None
    canonical_outputs: tuple[tuple[Path, bytes | None], ...]
    retired_pointers: tuple[Path, ...]


def publish_homes(
    project_root: Path,
    mode: PublicationMode,
    *,
    directory: str | Path | None = None,
    changed_paths: list[str] | None = None,
    required_home: Path | None = None,
) -> PublicationRun:
    """Converge selected homes to the canonical main tip under the docs lease."""
    if (directory is None) == (changed_paths is None):
        raise ValueError(_HOME_SCOPE_REQUIRED)
    try:
        canonical_root = git_common_root(project_root).resolve()
        with docs_lease(DocsLockOperation.SYNCHRONIZATION):
            tip = _main_tip(canonical_root)
            if tip is None:
                return _failed_run(mode, _GIT_VERIFY_ERROR, PublicationRunFailure.MAIN_TIP_UNAVAILABLE)
            return _publish_under_lease(canonical_root, tip, mode, directory, changed_paths, required_home)
    except DocsLeaseTimeoutError as exc:
        return _failed_run(mode, str(exc), PublicationRunFailure.RUN_FAILED)
    except (GitCommandError, OSError, subprocess.CalledProcessError, ValueError, yaml.YAMLError) as exc:
        return _failed_run(mode, str(exc))


def _publish_under_lease(
    canonical_root: Path,
    tip: str,
    mode: PublicationMode,
    directory: str | Path | None,
    changed_paths: list[str] | None,
    required_home: Path | None,
) -> PublicationRun:
    """Discover, build, install and record the homes for one held tip."""
    source = TreeSource.recorded_commit(canonical_root, tip)
    tree_paths = list_tree_paths(source)
    all_homes = homes_at_or_beneath(_ROOT_RELATIVE_PATH, source)
    if required_home is not None and required_home not in {home.root for home in all_homes}:
        error = _HOME_NOT_COMMITTED.format(home=required_home.as_posix())
        return _failed_run(mode, error, PublicationRunFailure.HOME_NOT_COMMITTED)
    scoped_homes = _scoped_homes(source, tree_paths, directory, changed_paths)
    generations = _load_home_generations(canonical_root)
    global_home_exists = any(
        home.root == _ROOT_RELATIVE_PATH and home.kind is ConfigKind.GLOBAL and home.error is None for home in all_homes
    )
    results: dict[str, HomePublicationResult] = {}
    pending: list[tuple[TreeHome, _HomeCategory]] = []
    for home in scoped_homes:
        root_key = home.root.as_posix()
        if home.error is not None:
            results[root_key] = _skipped_home(home, tip, mode, _HOME_DECLARATION_FAILED.format(error=home.error))
            continue
        category = _home_category(home, global_home_exists)
        if category is None:
            kind = home.kind.value if home.kind is not None else _EMPTY_STRING
            error = _UNSUPPORTED_HOME_POSITION.format(kind=kind, root=root_key)
            results[root_key] = _skipped_home(home, tip, mode, error)
            continue
        if mode is PublicationMode.OWED and generations.get(root_key) == tip:
            results[root_key] = HomePublicationResult(home, tip, mode, HomePublicationOutcome.UNCHANGED)
            continue
        pending.append((home, category))
    if not pending:
        return _finish_run(canonical_root, tip, mode, results, generations, all_homes, tree_paths)

    with materialize_tree(source) as snapshot_root:
        project_homes = [(home, category) for home, category in pending if category is _HomeCategory.PROJECT]
        scoped_non_project: list[tuple[TreeHome, _HomeCategory]] = [
            (home, category) for home, category in pending if category is not _HomeCategory.PROJECT
        ]
        if project_homes:
            for home, _ in project_homes:
                result = _publish_project_home(canonical_root, snapshot_root, home, tip, mode)
                results[home.root.as_posix()] = result
        if scoped_non_project:
            _publish_global_and_tier_homes(
                canonical_root,
                snapshot_root,
                source,
                tree_paths,
                all_homes,
                scoped_non_project,
                tip,
                mode,
                results,
            )
    return _finish_run(canonical_root, tip, mode, results, generations, all_homes, tree_paths)


def _scoped_homes(
    source: TreeSource,
    tree_paths: list[str],
    directory: str | Path | None,
    changed_paths: list[str] | None,
) -> list[TreeHome]:
    """Select and de-duplicate the tree homes addressed by one caller."""
    if directory is not None:
        scope = Path(directory)
        homes = homes_at_or_beneath(scope, source)
        if scope != _ROOT_RELATIVE_PATH and _designated_tier_kind(scope) is not None:
            homes = [home for home in homes if home.root == scope]
    else:
        grouped = group_paths_by_owning_home_tolerant(changed_paths or [], source, tree_paths=set(tree_paths))
        homes = list(grouped)
    unique = {home.root.as_posix(): home for home in homes}
    return [unique[root] for root in sorted(unique)]


def _home_category(home: TreeHome, global_home_exists: bool) -> _HomeCategory | None:
    """Classify only home positions defined by the domain glossary."""
    if home.kind is ConfigKind.PROJECT and home.root == _ROOT_RELATIVE_PATH:
        return _HomeCategory.PROJECT
    if home.kind is ConfigKind.GLOBAL and home.root == _ROOT_RELATIVE_PATH:
        return _HomeCategory.GLOBAL
    tier_kind = _designated_tier_kind(home.root)
    if global_home_exists and tier_kind is not None and home.kind is tier_kind:
        return _HomeCategory.TIER
    return None


def _designated_tier_kind(home_root: Path) -> ConfigKind | None:
    """Return the tier kind authorized at a direct company or person home path."""
    if len(home_root.parts) != 2:
        return None
    if home_root.parts[0] == COMPANIES_ROOT.name:
        return ConfigKind.COMPANY
    if home_root.parts[0] == PEOPLE_DIR.name:
        return ConfigKind.PERSON
    return None


def _publish_project_home(
    canonical_root: Path,
    snapshot_root: Path,
    home: TreeHome,
    tip: str,
    mode: PublicationMode,
) -> HomePublicationResult:
    """Build and install one repository-root project home as an undoable unit."""
    distribution: DistributionBuild | None = None
    try:
        capabilities = resolve_capabilities(snapshot_root)
        written_indexes = build_all_indexes(snapshot_root) if capabilities.docs else []
        index_outputs = _reroot_written_outputs(written_indexes, snapshot_root, canonical_root)
        distribution = distribute_committed(
            snapshot_root,
            canonical_root,
            agents_enabled=capabilities.agents,
            docs_enabled=capabilities.docs,
        )
        retired_outputs = (
            _retractable_outputs(snapshot_root, canonical_root, committed_retired_outputs(snapshot_root))
            if capabilities.docs
            else []
        )
        outputs = [
            *index_outputs,
            *((source, source.read_bytes()) for source in distribution.outputs),
            *((retired, None) for retired in retired_outputs),
        ]
    except _BUILD_FAILURES as exc:
        if distribution is not None:
            distribution.undo()
        return _skipped_home(home, tip, mode, _HOME_BUILD_FAILED.format(error=exc), canonical_root, snapshot_root)

    try:
        distribution.deploy()
        if outputs:
            _install_canonical_files(snapshot_root, canonical_root, outputs)
        retract_retired_pointers(
            snapshot_root=snapshot_root,
            canonical_root=canonical_root,
            candidates=distribution.retired_pointers,
        )
        if capabilities.docs and is_mother_project(snapshot_root):
            failed_refreshes = refresh_home_entrypoints(TELECLAUDE_HOME)
            if failed_refreshes:
                return HomePublicationResult(
                    home,
                    tip,
                    mode,
                    HomePublicationOutcome.FAILED,
                    _HOME_INSTALL_FAILED.format(
                        error=_ERROR_SEPARATOR.join(path.as_posix() for path in failed_refreshes)
                    ),
                )
    except _BUILD_FAILURES as exc:
        return HomePublicationResult(
            home, tip, mode, HomePublicationOutcome.FAILED, _HOME_INSTALL_FAILED.format(error=exc)
        )
    return HomePublicationResult(home, tip, mode, HomePublicationOutcome.PUBLISHED)


def _publish_global_and_tier_homes(
    canonical_root: Path,
    snapshot_root: Path,
    source: TreeSource,
    tree_paths: list[str],
    all_homes: list[TreeHome],
    scoped_homes: list[tuple[TreeHome, _HomeCategory]],
    tip: str,
    mode: PublicationMode,
    results: dict[str, HomePublicationResult],
) -> None:
    """Build every scoped global and tier home before installing any of them."""
    built: dict[str, _BuiltHome] = {}
    for home, category in scoped_homes:
        try:
            built_home = _build_tree_home(snapshot_root, canonical_root, home, category)
            built[home.root.as_posix()] = built_home
        except _BUILD_FAILURES as exc:
            results[home.root.as_posix()] = _skipped_home(
                home,
                tip,
                mode,
                _HOME_BUILD_FAILED.format(error=exc),
                canonical_root,
                snapshot_root,
                source,
                tree_paths,
            )

    global_key = _ROOT_RELATIVE_PATH.as_posix()
    global_build = built.get(global_key)
    try:
        retracted = _retracted_tier_identities(all_homes) if global_build is not None else set()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        if global_build is not None:
            results[global_key] = _skipped_home(
                global_build.home,
                tip,
                mode,
                _HOME_BUILD_FAILED.format(error=exc),
                canonical_root,
                snapshot_root,
                source,
                tree_paths,
            )
            del built[global_key]
        retracted = set()

    installed: set[str] = set()
    for root_key, item in built.items():
        try:
            if item.canonical_outputs:
                _install_canonical_files(snapshot_root, canonical_root, list(item.canonical_outputs))
            retract_retired_pointers(
                snapshot_root=snapshot_root,
                canonical_root=canonical_root,
                candidates=item.retired_pointers,
            )
            installed.add(root_key)
        except _BUILD_FAILURES as exc:
            results[root_key] = HomePublicationResult(
                item.home,
                tip,
                mode,
                HomePublicationOutcome.FAILED,
                _HOME_INSTALL_FAILED.format(error=exc),
            )

    tier_homes = [item.tier for root_key, item in built.items() if root_key in installed and item.tier is not None]
    global_retractions = retracted if global_key in installed else set()
    affected_tiers = {home.root.as_posix() for home in tier_homes}
    shared_generation_homes = set(affected_tiers)
    if global_retractions:
        shared_generation_homes.add(global_key)
    if tier_homes or global_retractions:
        try:
            distribute_tier_homes(tier_homes, global_retractions)
        except _BUILD_FAILURES as exc:
            for root_key in shared_generation_homes:
                item = built[root_key]
                results[root_key] = HomePublicationResult(
                    item.home,
                    tip,
                    mode,
                    HomePublicationOutcome.FAILED,
                    _HOME_INSTALL_FAILED.format(error=exc),
                )
            installed.difference_update(shared_generation_homes)

    for root_key, item in built.items():
        if root_key in installed:
            results[root_key] = HomePublicationResult(item.home, tip, mode, HomePublicationOutcome.PUBLISHED)


def _build_tree_home(
    snapshot_root: Path,
    canonical_root: Path,
    home: TreeHome,
    category: _HomeCategory,
) -> _BuiltHome:
    """Build indexes and home entrypoints for one global or tier home."""
    if home.kind is None:
        raise ValueError(_HOME_DECLARATION_FAILED.format(error=home.error))
    home_root = snapshot_root / home.root
    tier_participates = category is _HomeCategory.TIER and resolve_tier_permissions(home_root).participates_in(
        PermissionSurface.DOCUMENTATION
    )
    tier = TierHome(root=home_root, kind=home.kind, slug=home.root.name) if tier_participates else None
    written_indexes = build_tier_index(home_root, home.kind) if tier is not None else []
    index_outputs = _reroot_written_outputs(written_indexes, snapshot_root, canonical_root)
    entrypoints = inflate_home_entrypoints(home_root, home.kind)
    output_bytes = tuple((entrypoint.output, entrypoint.text.encode(_UTF8)) for entrypoint in entrypoints.entrypoints)
    return _BuiltHome(
        home=home,
        category=category,
        tier=tier,
        canonical_outputs=tuple([*index_outputs, *output_bytes]),
        retired_pointers=entrypoints.retired_pointers,
    )


def _retracted_tier_identities(all_homes: list[TreeHome]) -> set[tuple[ConfigKind, str]]:
    """Find deployed tier contributions whose declaration no longer exists in the tip tree."""
    deployed = deployed_tier_identities()
    present: set[tuple[ConfigKind, str]] = set()
    for home in all_homes:
        tier_kind = _designated_tier_kind(home.root)
        if tier_kind is not None and (home.error is not None or home.kind is tier_kind):
            present.add((tier_kind, home.root.name))
    return deployed - present


def _skipped_home(
    home: TreeHome,
    tip: str,
    mode: PublicationMode,
    error: str,
    canonical_root: Path | None = None,
    snapshot_root: Path | None = None,
    source: TreeSource | None = None,
    tree_paths: list[str] | None = None,
) -> HomePublicationResult:
    """Build a skipped result and run the shared diagnostic grade when substrate is available."""
    diagnostic: LintGateResult | None = None
    diagnostic_error: str | None = None
    if canonical_root is not None and snapshot_root is not None and source is not None and tree_paths is not None:
        logger.info(_HOME_DIAGNOSTIC_EVENT, home=home.root.as_posix())
        try:
            grouped = group_paths_by_owning_home_tolerant(tree_paths, source, tree_paths=set(tree_paths))
            candidates = next(
                (paths for entry, paths in grouped.items() if entry.root == home.root),
                [],
            )
            diagnostic = run_home_guardrail_gate(
                canonical_root,
                home.root,
                candidates,
                [],
                None,
                content_root=snapshot_root,
                platform_home_subject=is_platform_home(canonical_root),
            )
        except Exception as exc:
            diagnostic_error = _HOME_DIAGNOSTIC_FAILED.format(error=exc)
    return HomePublicationResult(
        home,
        tip,
        mode,
        HomePublicationOutcome.SKIPPED,
        error,
        diagnostic,
        diagnostic_error,
    )


def refresh_home_entrypoints(home: Path) -> list[Path]:
    """Refresh platform entrypoints from the per-home commits recorded by the platform home."""
    failures: list[Path] = []
    state = _load_home_generations(home)
    if not state:
        logger.info(_HOME_REFRESH_SKIPPED_EVENT, home=str(home), reason=_NO_PUBLISHED_HOME_GENERATIONS)
        return failures
    roots_by_commit: dict[str, list[str]] = {}
    for root_key, commit in state.items():
        roots_by_commit.setdefault(commit, []).append(root_key)
    for commit, roots in sorted(roots_by_commit.items()):
        source = TreeSource.recorded_commit(home, commit)
        try:
            with materialize_tree(source) as snapshot_root:
                for root_key in sorted(roots):
                    _refresh_one_home(home, snapshot_root, source, root_key, commit, failures)
        except (GitCommandError, OSError, subprocess.CalledProcessError, ValueError, yaml.YAMLError) as exc:
            logger.error(_HOME_REFRESH_FAILED_EVENT, home=str(home), published_generation=commit, cause=str(exc))
            failures.extend(Path(root_key) for root_key in roots)
    return failures


def _refresh_one_home(
    canonical_root: Path,
    snapshot_root: Path,
    source: TreeSource,
    root_key: str,
    commit: str,
    failures: list[Path],
) -> None:
    """Refresh every compilable master in one recorded home, preserving failures."""
    try:
        declared = [entry for entry in homes_at_or_beneath(Path(root_key), source) if entry.root.as_posix() == root_key]
        if not declared or declared[0].error is not None or declared[0].kind is None:
            failures.append(Path(root_key))
            return
        home_root = snapshot_root / Path(root_key)
        masters = home_masters(home_root, declared[0].kind)
        entrypoints: list[HomeEntrypoint] = []
        for master, read_root in masters:
            try:
                entrypoints.append(inflate_home_entrypoint(master, project_root=read_root, observation=None))
            except HomeMasterInflationError as exc:
                relative = master.relative_to(snapshot_root)
                logger.error(
                    _HOME_REFRESH_FAILED_EVENT,
                    home=root_key,
                    published_generation=commit,
                    master=relative.as_posix(),
                    cause=str(exc.cause),
                )
                failures.append(relative)
        outputs = [(item.output, item.text.encode(_UTF8)) for item in entrypoints]
        if outputs:
            _install_canonical_files(snapshot_root, canonical_root, outputs)
        retract_retired_pointers(
            snapshot_root=snapshot_root,
            canonical_root=canonical_root,
            candidates=[retired_pointer_candidate(master.parent) for master, _ in masters],
        )
    except (GitCommandError, OSError, subprocess.CalledProcessError, ValueError, yaml.YAMLError) as exc:
        logger.error(_HOME_REFRESH_FAILED_EVENT, home=root_key, published_generation=commit, cause=str(exc))
        failures.append(Path(root_key))


def _finish_run(
    canonical_root: Path,
    tip: str,
    mode: PublicationMode,
    results: dict[str, HomePublicationResult],
    generations: dict[str, str],
    all_homes: list[TreeHome],
    tree_paths: list[str],
) -> PublicationRun:
    """Persist completed homes, retire removed tier records, and emit run summaries."""
    current_state = dict(generations)
    for root_key, result in results.items():
        if result.outcome is HomePublicationOutcome.PUBLISHED:
            current_state[root_key] = tip
    global_result = results.get(_ROOT_RELATIVE_PATH.as_posix())
    if global_result is not None and global_result.outcome is HomePublicationOutcome.PUBLISHED:
        current_tier_roots = _tree_tier_root_keys(all_homes)
        for root_key in list(current_state):
            candidate = Path(root_key)
            if _designated_tier_kind(candidate) is not None:
                if root_key not in current_tier_roots:
                    del current_state[root_key]
    has_published_home = any(result.outcome is HomePublicationOutcome.PUBLISHED for result in results.values())
    state_file_missing = not _home_generations_path(canonical_root).is_file()
    if current_state != generations or (state_file_missing and has_published_home):
        _write_home_generations(canonical_root, current_state)
    ordered = tuple(results[root] for root in sorted(results))
    for result in ordered:
        logger.info(
            _HOME_PUBLICATION_EVENT,
            home=result.home.root.as_posix(),
            kind=result.home.kind.value if result.home.kind is not None else None,
            tip=result.tip,
            mode=result.mode.value,
            outcome=result.outcome.value,
            error=result.error,
            diagnostic_error=result.diagnostic_error,
        )
    counts = {outcome: sum(result.outcome is outcome for result in ordered) for outcome in HomePublicationOutcome}
    run = PublicationRun(tip=tip, mode=mode, homes=ordered)
    logger.info(
        _HOME_PUBLICATION_RUN_EVENT,
        repository_root=str(canonical_root),
        tip=tip,
        mode=mode.value,
        outcomes=counts,
        exit_code=run.exit_code,
    )
    return run


def _tree_tier_root_keys(homes: list[TreeHome]) -> set[str]:
    """Return current tree roots that hold or reserve a tier deployment identity."""
    roots: set[str] = set()
    for home in homes:
        tier_kind = _designated_tier_kind(home.root)
        if tier_kind is not None and (home.error is not None or home.kind is tier_kind):
            roots.add(home.root.as_posix())
    return roots


def _load_home_generations(canonical_root: Path) -> dict[str, str]:
    """Read current per-home state or seed it only from proven legacy completion."""
    state_path = _home_generations_path(canonical_root)
    if state_path.is_file():
        payload = yaml.safe_load(state_path.read_text(encoding=_UTF8))
        if not isinstance(payload, dict):
            raise ValueError(_INVALID_HOME_STATE.format(path=state_path))
        generations: dict[str, str] = {}
        for root, commit in payload.items():
            if not isinstance(root, str) or not isinstance(commit, str) or not _COMMIT_ID_PATTERN.fullmatch(commit):
                raise ValueError(_INVALID_HOME_STATE_ENTRY.format(root=root))
            generations[root] = commit
        return generations

    generations = {}
    if is_platform_home(canonical_root):
        legacy_published = _read_publication_id(
            canonical_root / _STATE_DIRECTORY / _PUBLICATION_DIRECTORY / _PUBLISHED_GENERATION_FILENAME
        )
        legacy_entrypoints = _read_publication_id(
            canonical_root / _STATE_DIRECTORY / _PUBLICATION_DIRECTORY / _ENTRYPOINTS_GENERATION_FILENAME
        )
        if legacy_published is not None and legacy_published == legacy_entrypoints:
            legacy_source = TreeSource.recorded_commit(canonical_root, legacy_published)
            for home in homes_at_or_beneath(_ROOT_RELATIVE_PATH, legacy_source):
                generations[home.root.as_posix()] = legacy_published
    return generations


def _write_home_generations(canonical_root: Path, generations: dict[str, str]) -> None:
    """Atomically persist per-home generations and retire the legacy state files."""
    state_path = _home_generations_path(canonical_root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_name(state_path.name + _PUBLICATION_NEXT_SUFFIX)
    temporary.write_text(yaml.safe_dump(dict(sorted(generations.items())), sort_keys=True), encoding=_UTF8)
    os.replace(temporary, state_path)
    legacy_directory = canonical_root / _STATE_DIRECTORY / _PUBLICATION_DIRECTORY
    for name in (_PUBLISHED_GENERATION_FILENAME, _UNFINISHED_PUBLICATION_FILENAME, _ENTRYPOINTS_GENERATION_FILENAME):
        (legacy_directory / name).unlink(missing_ok=True)


def _home_generations_path(canonical_root: Path) -> Path:
    """Return the single per-repository home-generation state file."""
    return canonical_root / _STATE_DIRECTORY / _PUBLICATION_DIRECTORY / _HOME_GENERATIONS_FILENAME


def _read_publication_id(path: Path) -> str | None:
    """Read one legacy publication id, or no value when it has never been written."""
    try:
        return path.read_text(encoding=_UTF8).strip()
    except FileNotFoundError:
        return None


def _main_tip(canonical_root: Path) -> str | None:
    """Resolve the canonical main ref to a full commit id."""
    try:
        tip = cast(str, Repo(str(canonical_root)).git.rev_parse(*_GIT_MAIN_TIP_ARGS)).strip()
    except GitCommandError:
        return None
    return tip if _COMMIT_ID_PATTERN.fullmatch(tip) else None


def _failed_run(
    mode: PublicationMode,
    error: str,
    failure: PublicationRunFailure = PublicationRunFailure.RUN_FAILED,
) -> PublicationRun:
    """Return a run-level failure when publication could not reach home execution."""
    run = PublicationRun(tip=None, mode=mode, homes=(), error=error, failure=failure)
    logger.error(_HOME_PUBLICATION_RUN_EVENT, mode=mode.value, error=error, exit_code=run.exit_code)
    return run


def _reroot_written_outputs(
    written: list[Path], snapshot_root: Path, canonical_root: Path
) -> list[tuple[Path, bytes | None]]:
    """Pair snapshot-written indexes with their canonical-rooted bytes."""
    return [
        (
            source,
            reroot_index_document(source.read_text(encoding=_UTF8), snapshot_root, canonical_root).encode(_UTF8)
            if source.is_file()
            else None,
        )
        for source in written
    ]


def _retractable_outputs(snapshot_root: Path, canonical_root: Path, candidates: list[Path]) -> list[Path]:
    """Keep only retired outputs the canonical checkout owns as ignored, untracked files."""
    if not candidates:
        return []
    relative = [candidate.relative_to(snapshot_root).as_posix() for candidate in candidates]
    output = Repo(str(canonical_root)).git.ls_files(*_GIT_IGNORED_UNTRACKED_ARGS, *relative)
    eligible = set(output.split(_GIT_PATH_SEPARATOR))
    return [candidate for candidate, path in zip(candidates, relative, strict=True) if path in eligible]


def _install_canonical_files(
    snapshot_root: Path,
    canonical_root: Path,
    outputs: Iterable[tuple[Path, bytes | None]],
) -> None:
    """Atomically install snapshot outputs onto the canonical checkout."""
    staged: list[tuple[Path, Path | None]] = []
    for source, payload in outputs:
        destination = canonical_root / source.relative_to(snapshot_root)
        previous_payload = destination.read_bytes() if destination.is_file() else None
        if payload is not None:
            if payload == previous_payload:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + _PUBLICATION_NEXT_SUFFIX)
            temporary.write_bytes(payload)
            staged.append((destination, temporary))
        elif previous_payload is not None:
            staged.append((destination, None))
    for destination, temporary in staged:
        if temporary is None:
            destination.unlink(missing_ok=True)
        else:
            os.replace(temporary, destination)
