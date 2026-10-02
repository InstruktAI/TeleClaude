"""Converge the TeleClaude home into a local-only retained history."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryFile
from typing import cast

from git.index.typ import IndexEntry
from instrukt_ai_logging import get_logger

from teleclaude.core.reconciliation.home_convergence import home_installation_targets
from teleclaude.core.reconciliation.home_retained_set import (
    HomeMembership,
    historical_home_membership,
    home_membership,
    home_retained_set_digest,
    home_retained_set_path,
)
from teleclaude.core.reconciliation.template_installation import (
    HomeTemplateDisposition,
    HomeTemplateOutcome,
    materialize_template_targets,
)
from teleclaude.git import (
    GIT_EXECUTABLE,
    GitCommandError,
    HookExecutionError,
    InvalidGitRepositoryError,
    NoSuchPathError,
    Repo,
)
from teleclaude.paths import (
    BIN_DIR,
    COMPANIES_ROOT,
    ENV_PATH,
    GLOBAL_DOCS_DIR,
    GLOBAL_SKILLS_DIR,
    LOGS_DIR,
    PEOPLE_DIR,
    SESSION_AUTH_DIR,
    SHELL_DIR,
    SKILL_STORE_DIR,
    STATE_DIR,
    TELECLAUDE_HOME,
    TMP_SESSIONS_DIR,
)
from teleclaude.project_setup.git_filters import ensure_git_filters
from teleclaude.project_setup.hooks import install_code_hooks


class HomeActivationStatus(StrEnum):
    """Closed outcomes for one home-repository activation attempt."""

    ACTIVATED = "activated"
    REFUSED = "refused"
    GATE_REFUSED = "gate_refused"


class HomePathClass(StrEnum):
    """Privacy-safe categories emitted with home-repository observations."""

    AUTHORED_CONFIG = "authored_config"
    PERSON_MATERIAL = "person_material"
    COMPANY_MATERIAL = "company_material"
    SECRET = "secret"
    RUNTIME_STATE = "runtime_state"
    PROJECTION = "projection"
    LINK = "link"
    FOREIGN_ROOT = "foreign_root"


class HomeActivationReason(StrEnum):
    """Closed reasons emitted with activation outcomes."""

    CONVERGED = "converged"
    UNRETAINED_CANDIDATE = "unretained_candidate"
    RECORDED_BREACH = "recorded_breach"
    COMMIT_GATE_REFUSED = "commit_gate_refused"


@dataclass(frozen=True)
class HomeActivationResult:
    """Operator-relevant activation result, including any commit-gate findings."""

    status: HomeActivationStatus
    refused_paths: tuple[Path, ...]
    breach_paths: tuple[Path, ...]
    created_repository: bool
    recorded_paths: int
    gate_findings: tuple[str, ...] = ()


_LOGGER = get_logger("teleclaude.reconciliation.home_repository")
_NUL = "\0"
_NUL_BYTES = b"\0"
_LS_FILES_OTHERS_OPTION = "--others"
_LS_FILES_EXCLUDE_STANDARD_OPTION = "--exclude-standard"
_LS_FILES_NUL_OPTION = "-z"
_LS_TREE_RECURSIVE_OPTION = "-r"
_REMOTE_CONFIG_SECTION_PREFIX = "remote."
_PUBLICATION_DESTINATION_CONFIG_PATTERN = r"^(branch\..*\.(remote|pushremote)|remote\.pushdefault)$"
_GIT_CONFIG_NO_MATCH_STATUS = 1
_ENV_NAME = ENV_PATH.name
_RUNTIME_DIRECTORIES = frozenset((STATE_DIR.name, LOGS_DIR.name, SESSION_AUTH_DIR.name, TMP_SESSIONS_DIR.parent.name))
_PROJECTION_DIRECTORIES = frozenset(
    (
        GLOBAL_DOCS_DIR.name,
        SKILL_STORE_DIR.name,
        BIN_DIR.name,
        SHELL_DIR.name,
        GLOBAL_SKILLS_DIR.name,
    )
)
_PEOPLE_DIRECTORY = PEOPLE_DIR.name
_COMPANIES_DIRECTORY = COMPANIES_ROOT.name
_GIT_DIRECTORY = ".git"
_ACTIVATION_COMMIT_MESSAGE = "Activate local TeleClaude home history"
_PRE_COMMIT_HOOK_NAME = "pre-commit"
_ACTIVATION_EVENT = "home_repository_activation"
_BREACH_EVENT = "home_repository_breach"
_REFUSAL_EVENT = "home_repository_refused"
_GATE_REFUSAL_EVENT = "home_repository_gate_refused"
_COUNT_FIELD = "candidate_count"
_BREACH_COUNT_FIELD = "breach_count"
_DECLARATION_DIGEST_FIELD = "declaration_digest"
_OUTCOME_FIELD = "outcome"
_REASON_FIELD = "reason"
_PATH_CLASSES_FIELD = "path_classes"
_TEMPLATES_WRITTEN_FIELD = "templates_written"
_TEMPLATES_PRESERVED_FIELD = "templates_preserved"
_GATE_FINDINGS_FIELD = "gate_findings"
_GIT_INDEX_INFO_FLAG = "--index-info"
_GIT_FORCE_REMOVE_FLAG = "--force-remove"
_GIT_STDIN_FLAG = "--stdin"
_GIT_NUL_FLAG = "-z"
_GIT_LITERAL_PATHSPECS_ARGUMENT = "--literal-pathspecs"
_GIT_UPDATE_INDEX_COMMAND = "update-index"
_GATE_REFUSAL_FALLBACK = "The commit gate refused activation without diagnostic output."
_UTF8 = "utf-8"
_ASCII = "ascii"
_REPLACEMENT = "replace"
_HOOK_STDERR_FIELD_PREFIX = "\n  stderr: '"
_HOOK_STDOUT_FIELD_PREFIX = "\n  stdout: '"
_HOOK_FIELD_SUFFIX = "'"


def activate_home_repository(home: Path = TELECLAUDE_HOME) -> HomeActivationResult:
    """Establish or converge the local-only history rooted at ``home``.

    Every home and enabled help desk is first converged to its templates; the
    commit hooks are installed before staging retained candidates and files the
    convergence rewrote. A pre-commit refusal returns its findings and restores
    the index entries activation touched, leaving installation non-fatal.
    """
    home.mkdir(parents=True, exist_ok=True)
    outcomes = materialize_template_targets(home_installation_targets(home), values={}, environ=os.environ)  # fmt: skip  # guard: direct-env-read - allowed: configuration loading or interpolation
    repository, created_repository = _repository_at_home(home)
    _remove_remotes(repository)
    candidates = _activation_candidates(repository, home=home)
    refused_paths = _unretained_paths(candidates, home=home)
    if refused_paths:
        _log_refusal(refused_paths, home=home)
        return HomeActivationResult(
            status=HomeActivationStatus.REFUSED,
            refused_paths=refused_paths,
            breach_paths=(),
            created_repository=created_repository,
            recorded_paths=0,
        )
    install_code_hooks(home)
    recorded = tuple(sorted({*candidates, *_refreshed_retained_paths(outcomes, home=home)}))
    if recorded:
        prior_entries = _index_entries_for_paths(repository, recorded)
        repository.index.add([path.as_posix() for path in recorded])
        if _index_requires_commit(repository):
            try:
                repository.index.commit(_ACTIVATION_COMMIT_MESSAGE)
            except HookExecutionError as error:
                if Path(error.command[0]).name != _PRE_COMMIT_HOOK_NAME:
                    raise
                _restore_index_entries(repository, recorded, prior_entries)
                findings = _hook_findings(error)
                _log_gate_refusal(findings)
                return HomeActivationResult(
                    status=HomeActivationStatus.GATE_REFUSED,
                    refused_paths=(),
                    breach_paths=(),
                    created_repository=created_repository,
                    recorded_paths=0,
                    gate_findings=findings,
                )
    ensure_git_filters(home, enabled=True)
    breach_paths = _recorded_breaches(repository, home=home)
    _log_completion(recorded, breach_paths, outcomes, home=home)
    return HomeActivationResult(
        status=HomeActivationStatus.ACTIVATED,
        refused_paths=(),
        breach_paths=breach_paths,
        created_repository=created_repository,
        recorded_paths=len(recorded),
    )


def _index_entries_for_paths(repository: Repo, paths: tuple[Path, ...]) -> dict[tuple[str, int], IndexEntry]:
    """Snapshot prior index entries for only the paths activation will stage."""
    selected = {path.as_posix() for path in paths}
    entries: dict[tuple[str, int], IndexEntry] = {}
    for key, entry in repository.index.entries.items():
        path = os.fsdecode(key[0])
        if path in selected:
            entries[(path, key[1])] = entry
    return entries


def _restore_index_entries(
    repository: Repo,
    paths: tuple[Path, ...],
    prior_entries: dict[tuple[str, int], IndexEntry],
) -> None:
    """Restore activation paths with Git while retaining all other index entries."""
    path_stream = b"".join(os.fsencode(path.as_posix()) + _NUL_BYTES for path in paths)
    _run_index_update(
        repository,
        (_GIT_NUL_FLAG, _GIT_FORCE_REMOVE_FLAG, _GIT_STDIN_FLAG),
        path_stream,
    )
    if not prior_entries:
        return
    records: list[bytes] = []
    for (path, stage), entry in sorted(prior_entries.items()):
        record = f"{entry.mode:o} {entry.hexsha} {stage}\t".encode(_ASCII) + os.fsencode(path)
        records.append(record + _NUL_BYTES)
    if records:
        _run_index_update(repository, (_GIT_NUL_FLAG, _GIT_INDEX_INFO_FLAG), b"".join(records))


def _run_index_update(repository: Repo, arguments: Sequence[str], payload: bytes) -> None:
    """Feed a NUL-delimited index operation through a file-backed GitPython stream."""
    with TemporaryFile() as stream:
        stream.write(payload)
        stream.seek(0)
        execute = cast(Callable[..., object], repository.git.execute)
        execute(
            [GIT_EXECUTABLE, _GIT_LITERAL_PATHSPECS_ARGUMENT, _GIT_UPDATE_INDEX_COMMAND, *arguments],
            istream=stream,
        )


def _hook_findings(error: HookExecutionError) -> tuple[str, ...]:
    """Return gate diagnostics from GitPython's hook exception."""
    diagnostic = error.stderr or error.stdout
    field_prefix = _HOOK_STDERR_FIELD_PREFIX if error.stderr else _HOOK_STDOUT_FIELD_PREFIX
    if isinstance(diagnostic, bytes):
        text = diagnostic.decode(_UTF8, errors=_REPLACEMENT)
    elif diagnostic:
        text = str(diagnostic)
    else:
        text = str(error)
    if text.startswith(field_prefix) and text.endswith(_HOOK_FIELD_SUFFIX):
        text = text[len(field_prefix) : -len(_HOOK_FIELD_SUFFIX)]
    findings = tuple(line for line in text.splitlines() if line)
    return findings or (_GATE_REFUSAL_FALLBACK,)


def _log_gate_refusal(findings: tuple[str, ...]) -> None:
    """Record a refused activation with the gate's findings."""
    _LOGGER.info(
        _GATE_REFUSAL_EVENT,
        extra={
            _ACTIVATION_EVENT: _GATE_REFUSAL_EVENT,
            _OUTCOME_FIELD: HomeActivationStatus.GATE_REFUSED,
            _REASON_FIELD: HomeActivationReason.COMMIT_GATE_REFUSED,
            _GATE_FINDINGS_FIELD: findings,
        },
    )


def _refreshed_retained_paths(outcomes: tuple[HomeTemplateOutcome, ...], *, home: Path) -> tuple[Path, ...]:
    """Home-relative retained targets that template convergence wrote."""
    return tuple(
        outcome.target.relative_to(home)
        for outcome in outcomes
        if outcome.disposition is HomeTemplateDisposition.WRITTEN
        and outcome.target.is_relative_to(home)
        and home_membership(outcome.target, home=home) is HomeMembership.RETAINED
    )


def _repository_at_home(home: Path) -> tuple[Repo, bool]:
    try:
        return Repo(home, search_parent_directories=False), False
    except (InvalidGitRepositoryError, NoSuchPathError):
        return Repo.init(home), True


def _remove_remotes(repository: Repo) -> None:
    for remote in repository.remotes:
        repository.git.config("--local", "--remove-section", f"{_REMOTE_CONFIG_SECTION_PREFIX}{remote.name}")
    for setting in _publication_destination_settings(repository):
        repository.git.config("--local", "--unset-all", setting)


def _publication_destination_settings(repository: Repo) -> tuple[str, ...]:
    try:
        output = repository.git.config(
            "--local",
            "--name-only",
            "--get-regexp",
            _PUBLICATION_DESTINATION_CONFIG_PATTERN,
        )
    except GitCommandError as error:
        if error.status == _GIT_CONFIG_NO_MATCH_STATUS:
            return ()
        raise
    return tuple(dict.fromkeys(output.splitlines()))


def _activation_candidates(repository: Repo, *, home: Path) -> tuple[Path, ...]:
    output = repository.git.ls_files(
        _LS_FILES_OTHERS_OPTION,
        _LS_FILES_EXCLUDE_STANDARD_OPTION,
        _LS_FILES_NUL_OPTION,
    )
    candidates = {Path(candidate) for candidate in output.split(_NUL) if candidate}
    candidates.add(home_retained_set_path(home).relative_to(home))
    return tuple(sorted(candidates))


def _index_requires_commit(repository: Repo) -> bool:
    return not repository.head.is_valid() or repository.is_dirty(
        index=True,
        working_tree=False,
        untracked_files=False,
    )


def _unretained_paths(candidates: tuple[Path, ...], *, home: Path) -> tuple[Path, ...]:
    return tuple(
        candidate
        for candidate in candidates
        if home_membership(home / candidate, home=home) is not HomeMembership.RETAINED
    )


def _recorded_breaches(repository: Repo, *, home: Path) -> tuple[Path, ...]:
    breaches = {
        path
        for path, mode in _recorded_tree_paths(repository)
        if historical_home_membership(path, mode=mode, home=home) is not HomeMembership.RETAINED
    }
    return tuple(sorted(breaches))


def _recorded_tree_paths(repository: Repo) -> tuple[tuple[Path, str], ...]:
    paths: set[tuple[Path, str]] = set()
    for revision in repository.git.rev_list("--all").splitlines():
        tree = repository.git.ls_tree(_LS_TREE_RECURSIVE_OPTION, _LS_FILES_NUL_OPTION, revision)
        paths.update(_tree_paths(tree))
    return tuple(sorted(paths))


def _tree_paths(tree: str) -> tuple[tuple[Path, str], ...]:
    paths: list[tuple[Path, str]] = []
    for entry in tree.split(_NUL):
        if not entry:
            continue
        metadata, raw_path = entry.split("\t", maxsplit=1)
        mode, _kind, _object_id = metadata.split(" ", maxsplit=2)
        paths.append((Path(raw_path), mode))
    return tuple(paths)


def _log_refusal(refused_paths: tuple[Path, ...], *, home: Path) -> None:
    _LOGGER.info(
        _REFUSAL_EVENT,
        extra={
            _ACTIVATION_EVENT: _REFUSAL_EVENT,
            _COUNT_FIELD: len(refused_paths),
            _DECLARATION_DIGEST_FIELD: home_retained_set_digest(),
            _OUTCOME_FIELD: HomeActivationStatus.REFUSED,
            _REASON_FIELD: HomeActivationReason.UNRETAINED_CANDIDATE,
            _PATH_CLASSES_FIELD: tuple(_path_class(path, home=home) for path in refused_paths),
        },
    )


def _log_completion(
    recorded: tuple[Path, ...],
    breach_paths: tuple[Path, ...],
    outcomes: tuple[HomeTemplateOutcome, ...],
    *,
    home: Path,
) -> None:
    _LOGGER.info(
        _ACTIVATION_EVENT,
        extra={
            _ACTIVATION_EVENT: _ACTIVATION_EVENT,
            _COUNT_FIELD: len(recorded),
            _BREACH_COUNT_FIELD: len(breach_paths),
            _TEMPLATES_WRITTEN_FIELD: _count_disposition(outcomes, HomeTemplateDisposition.WRITTEN),
            _TEMPLATES_PRESERVED_FIELD: _count_disposition(outcomes, HomeTemplateDisposition.PRESERVED),
            _DECLARATION_DIGEST_FIELD: home_retained_set_digest(),
            _OUTCOME_FIELD: HomeActivationStatus.ACTIVATED,
            _REASON_FIELD: HomeActivationReason.CONVERGED,
        },
    )
    if breach_paths:
        _LOGGER.info(
            _BREACH_EVENT,
            extra={
                _ACTIVATION_EVENT: _BREACH_EVENT,
                _BREACH_COUNT_FIELD: len(breach_paths),
                _DECLARATION_DIGEST_FIELD: home_retained_set_digest(),
                _OUTCOME_FIELD: HomeActivationStatus.ACTIVATED,
                _REASON_FIELD: HomeActivationReason.RECORDED_BREACH,
                _PATH_CLASSES_FIELD: tuple(_path_class(path, home=home) for path in breach_paths),
            },
        )


def _count_disposition(outcomes: tuple[HomeTemplateOutcome, ...], disposition: HomeTemplateDisposition) -> int:
    return sum(1 for outcome in outcomes if outcome.disposition is disposition)


def _path_class(path: Path, *, home: Path) -> HomePathClass:
    absolute_path = home / path
    parts = path.parts
    if absolute_path.is_symlink():
        return HomePathClass.LINK
    if _GIT_DIRECTORY in parts:
        return HomePathClass.FOREIGN_ROOT
    if _ENV_NAME in parts:
        return HomePathClass.SECRET
    if any(directory in parts for directory in _RUNTIME_DIRECTORIES):
        return HomePathClass.RUNTIME_STATE
    if any(directory in parts for directory in _PROJECTION_DIRECTORIES):
        return HomePathClass.PROJECTION
    if _PEOPLE_DIRECTORY in parts:
        return HomePathClass.PERSON_MATERIAL
    if _COMPANIES_DIRECTORY in parts:
        return HomePathClass.COMPANY_MATERIAL
    return HomePathClass.AUTHORED_CONFIG
