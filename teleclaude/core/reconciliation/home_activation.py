"""Converge the TeleClaude home into a local-only retained history."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from typing import cast

from instrukt_ai_logging import get_logger

from teleclaude.core.reconciliation.home_convergence import home_installation_targets
from teleclaude.core.reconciliation.home_retained_set import (
    HomeMembership,
    historical_home_membership,
    home_membership,
    home_retained_set_digest,
)
from teleclaude.core.reconciliation.template_installation import (
    HomeTemplateDisposition,
    HomeTemplateOutcome,
    PlannedTemplateFile,
    TemplateInstallationPlan,
    apply_template_installation,
    plan_template_installation,
)
from teleclaude.git import (
    GIT_EXECUTABLE,
    Actor,
    GitCommandError,
    HookExecutionError,
    IndexFile,
    InvalidGitRepositoryError,
    NoSuchPathError,
    Repo,
    no_autostash_env,
)
from teleclaude.git_lock import main_branch_lock, wait_for_index_lock_clear
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
from teleclaude.project_setup.hooks import HookConvergenceOutcome, install_code_hooks


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
    held_paths: tuple[Path, ...] = ()
    unrestored_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class _RecordedGitEntry:
    mode: str
    object_id: str


@dataclass(frozen=True)
class _IndexGitEntry:
    mode: str
    object_id: str
    stage: int
    assume_unchanged: bool
    skip_worktree: bool


@dataclass(frozen=True)
class _TreeGitEntry:
    path: Path
    mode: str
    kind: str
    object_id: str


class _CommitGateUnavailable(RuntimeError):
    """The installed pre-commit gate cannot be executed by this commit path."""


_LOGGER = get_logger("teleclaude.reconciliation.home_repository")
_NUL = "\0"
_NUL_BYTES = b"\0"
_EMPTY_BYTES = b""
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
_POST_COMMIT_HOOK_NAME = "post-commit"
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
_TEMPLATES_HELD_FIELD = "templates_held"
_GATE_FINDINGS_FIELD = "gate_findings"
_GIT_INDEX_INFO_FLAG = "--index-info"
_GIT_NUL_FLAG = "-z"
_GIT_LITERAL_PATHSPECS_ARGUMENT = "--literal-pathspecs"
_GIT_UPDATE_INDEX_COMMAND = "update-index"
_GIT_LS_TREE_COMMAND = "ls-tree"
_GIT_LS_FILES_COMMAND = "ls-files"
_GIT_HASH_OBJECT_COMMAND = "hash-object"
_GIT_CONFIG_COMMAND = "config"
_GIT_READ_TREE_COMMAND = "read-tree"
_GIT_ADD_COMMAND = "add"
_GIT_ENV_OPTION = "env"
_GIT_REV_PARSE_COMMAND = "rev-parse"
_GIT_PATH_OPTION = "--git-path"
_PRE_COMMIT_HOOK_RELATIVE_PATH = "hooks/pre-commit"
_GITPYTHON_HOOKS_DIRECTORY = "hooks"
_GIT_BOOL_OPTION = "--bool"
_GIT_GET_OPTION = "--get"
_GIT_FORCE_OPTION = "--force"
_GIT_FILE_MODE_KEY = "core.filemode"
_GIT_HEAD_REVISION = "HEAD"
_GIT_EMPTY_TREE_OPTION = "--empty"
_TEMPORARY_INDEX_ENVIRONMENT_VARIABLE = "GIT_INDEX_FILE"
_TEMPORARY_INDEX_DIRECTORY_PREFIX = "teleclaude-home-activation-"
_TEMPORARY_INDEX_FILENAME = "index"
_GIT_BLOB_KIND = "blob"
_INDEX_STAGE_ZERO = "0"
_INDEX_INFO_RECORD = "{mode} {object_id} {stage}{tab}"
_GIT_TREE_METADATA_SEPARATOR = " "
_SKIP_WORKTREE_TAG = "S"
_WORKING_HASH_COUNT_ERROR = "git returned an unexpected number of working file object identifiers"
_COMMITTED_REVISION_MISSING_ERROR = "activation commit completed without a readable HEAD revision"
_CANDIDATE_TREE_ENTRY_INVALID_ERROR = "activation commit contains a non-blob candidate path"
_CANDIDATE_TREE_PATHS_MISMATCH_ERROR = "activation commit does not contain exactly its candidate paths"
_TEMPORARY_INDEX_CANDIDATES_MISSING_ERROR = "temporary index is missing an activation candidate"
_TRUE_VALUE = "true"
_GIT_STDIN_PATHS_OPTION = "--stdin-paths"
_GIT_STAGE_OPTION = "-s"
_GIT_VERBOSE_OPTION = "-v"
_GIT_LITERAL_PATHSPEC_PREFIX = ":(literal)"
_GIT_SEPARATOR = "--"
_INSTALLATION_IDENTITY_NAME = "TeleClaude installation"
_INSTALLATION_IDENTITY_EMAIL = "teleclaude@teleclaude.invalid"
_WORKING_FILE_MODE = "100755"
_WORKING_FILE_MODE_NON_EXECUTABLE = "100644"
_MODE_EXECUTABLE_BIT = stat.S_IXUSR
_NEWLINE_BYTES = b"\n"
_TAB = "\t"
_GATE_REFUSAL_FALLBACK = "The commit gate refused activation without diagnostic output."
_GATE_INSTALLATION_FAILED = "TeleClaude's pre-commit hook was not installed (outcome: {outcome})."
_GATE_HOOK_PATH_MISMATCH = "Git's configured pre-commit hook path differs from GitPython's hook path."
_GATE_HOOK_MISSING = "GitPython's pre-commit hook file is missing."
_GATE_HOOK_NOT_EXECUTABLE = "GitPython's pre-commit hook is not executable."
_GATE_VERIFICATION_FAILED = "Could not verify the installed pre-commit hook: {error}"
_MISSING_HOOK_OUTCOME = "missing"
_UTF8 = "utf-8"
_ASCII = "ascii"
_REPLACEMENT = "replace"
_HOOK_STDERR_FIELD_PREFIX = "\n  stderr: '"
_HOOK_STDOUT_FIELD_PREFIX = "\n  stdout: '"
_HOOK_FIELD_SUFFIX = "'"


def activate_home_repository(home: Path = TELECLAUDE_HOME) -> HomeActivationResult:
    """Establish or converge the local-only history rooted at ``home``.

    Every home and enabled help desk is first planned from its templates. Under
    the shared commit lock, activation holds unrecorded targets, applies the
    remaining writes, and records only those writes. A gate refusal restores
    activation's working-tree writes, leaving installation non-fatal.
    """
    home.mkdir(parents=True, exist_ok=True)
    repository, created_repository = _repository_at_home(home)
    _remove_remotes(repository)
    plan = plan_template_installation(home_installation_targets(home), values={}, environ=os.environ)  # fmt: skip  # guard: direct-env-read - allowed: configuration loading or interpolation
    hook_outcomes = install_code_hooks(home)
    held_paths: tuple[Path, ...] = ()
    unrestored_paths: tuple[Path, ...] = ()
    with main_branch_lock():
        wait_for_index_lock_clear(home)
        retained_files = tuple(
            file
            for target in plan.targets
            for file in target.files
            if home_membership(file.target, home=home) is HomeMembership.RETAINED
        )
        held_targets = _held_template_targets(repository, retained_files, home=home)
        held_paths = tuple(sorted(target.relative_to(home) for target in held_targets))
        prior_contents = _snapshot_template_contents(retained_files, held_targets, home=home)
        outcomes = apply_template_installation(plan, held_targets=frozenset(held_targets))
        recorded = _refreshed_retained_paths(outcomes, home=home)
        refused_paths = _unretained_paths(recorded, home=home)
        if refused_paths:
            _log_refusal(refused_paths, home=home)
            unrestored_paths = _restore_written_templates(
                recorded,
                plan,
                prior_contents,
                home=home,
            )
            return HomeActivationResult(
                status=HomeActivationStatus.REFUSED,
                refused_paths=refused_paths,
                breach_paths=(),
                created_repository=created_repository,
                recorded_paths=0,
                held_paths=held_paths,
                unrestored_paths=unrestored_paths,
            )
        if recorded:
            try:
                _require_commit_gate(repository, hook_outcomes)
                _commit_candidates(repository, recorded)
            except (_CommitGateUnavailable, HookExecutionError) as error:
                if isinstance(error, HookExecutionError):
                    if Path(error.command[0]).name != _PRE_COMMIT_HOOK_NAME:
                        raise
                    findings = _hook_findings(error)
                else:
                    findings = (str(error),)
                _log_gate_refusal(findings)
                unrestored_paths = _restore_written_templates(
                    recorded,
                    plan,
                    prior_contents,
                    home=home,
                )
                return HomeActivationResult(
                    status=HomeActivationStatus.GATE_REFUSED,
                    refused_paths=(),
                    breach_paths=(),
                    created_repository=created_repository,
                    recorded_paths=0,
                    gate_findings=findings,
                    held_paths=held_paths,
                    unrestored_paths=unrestored_paths,
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
        held_paths=held_paths,
    )


def _held_template_targets(
    repository: Repo,
    files: tuple[PlannedTemplateFile, ...],
    *,
    home: Path,
) -> set[Path]:
    """Return retained template targets whose current state is not clean or absent."""
    targets = tuple(file.target for file in files)
    relative_paths = tuple(target.relative_to(home) for target in targets)
    if not relative_paths:
        return set()
    recorded = _recorded_template_entries(repository, relative_paths)
    indexed = _indexed_template_entries(repository, relative_paths)
    present_paths = tuple(
        relative for relative, target in zip(relative_paths, targets) if target.is_file() and not target.is_symlink()
    )
    working = _working_template_hashes(repository, present_paths)
    file_mode_enabled = _core_file_mode_enabled(repository)
    held: set[Path] = set()
    for relative, target in zip(relative_paths, targets):
        recorded_entry = recorded.get(relative)
        index_entries = indexed.get(relative, ())
        exists = target.exists() or target.is_symlink()
        if not exists and recorded_entry is None and not index_entries:
            continue
        if (
            not target.is_file()
            or target.is_symlink()
            or recorded_entry is None
            or len(index_entries) != 1
            or relative not in working
        ):
            held.add(target)
            continue
        index_entry = index_entries[0]
        if (
            index_entry.stage != 0
            or index_entry.assume_unchanged
            or index_entry.skip_worktree
            or index_entry.mode != recorded_entry.mode
            or index_entry.object_id != recorded_entry.object_id
            or working[relative] != recorded_entry.object_id
        ):
            held.add(target)
            continue
        if file_mode_enabled and _working_file_mode(target) != recorded_entry.mode:
            held.add(target)
    return held


def _recorded_template_entries(repository: Repo, paths: tuple[Path, ...]) -> dict[Path, _RecordedGitEntry]:
    if not repository.head.is_valid():
        return {}
    pathspecs = tuple(_GIT_LITERAL_PATHSPEC_PREFIX + path.as_posix() for path in paths)
    output = _run_git_command(
        repository,
        (
            _GIT_LS_TREE_COMMAND,
            _LS_FILES_NUL_OPTION,
            _GIT_HEAD_REVISION,
            _GIT_SEPARATOR,
            *pathspecs,
        ),
    )
    entries: dict[Path, _RecordedGitEntry] = {}
    for entry in _parse_tree_entries(output):
        entries[entry.path] = _RecordedGitEntry(entry.mode, entry.object_id)
    return entries


def _indexed_template_entries(repository: Repo, paths: tuple[Path, ...]) -> dict[Path, tuple[_IndexGitEntry, ...]]:
    pathspecs = tuple(_GIT_LITERAL_PATHSPEC_PREFIX + path.as_posix() for path in paths)
    output = _run_git_command(
        repository,
        (
            _GIT_LS_FILES_COMMAND,
            _GIT_STAGE_OPTION,
            _GIT_VERBOSE_OPTION,
            _LS_FILES_NUL_OPTION,
            _GIT_SEPARATOR,
            *pathspecs,
        ),
    )
    entries: dict[Path, list[_IndexGitEntry]] = {}
    for record in output.split(_NUL):
        if not record:
            continue
        metadata, raw_path = record.split(_TAB, maxsplit=1)
        tag, mode, object_id, stage = metadata.split()
        index_entry = _IndexGitEntry(
            mode=mode,
            object_id=object_id,
            stage=int(stage),
            assume_unchanged=tag.islower(),
            skip_worktree=tag.upper() == _SKIP_WORKTREE_TAG,
        )
        entries.setdefault(Path(raw_path), []).append(index_entry)
    return {path: tuple(path_entries) for path, path_entries in entries.items()}


def _working_template_hashes(repository: Repo, paths: tuple[Path, ...]) -> dict[Path, str]:
    if not paths:
        return {}
    payload = _NEWLINE_BYTES.join(os.fsencode(path.as_posix()) for path in paths) + _NEWLINE_BYTES
    output = _run_git_command(repository, (_GIT_HASH_OBJECT_COMMAND, _GIT_STDIN_PATHS_OPTION), payload=payload)
    object_ids = output.splitlines()
    if len(object_ids) != len(paths):
        raise RuntimeError(_WORKING_HASH_COUNT_ERROR)
    return {path: object_id for path, object_id in zip(paths, object_ids)}


def _core_file_mode_enabled(repository: Repo) -> bool:
    try:
        return (
            _run_git_command(
                repository, (_GIT_CONFIG_COMMAND, _GIT_BOOL_OPTION, _GIT_GET_OPTION, _GIT_FILE_MODE_KEY)
            ).strip()
            == _TRUE_VALUE
        )
    except GitCommandError as error:
        if error.status == _GIT_CONFIG_NO_MATCH_STATUS:
            return True
        raise


def _working_file_mode(path: Path) -> str:
    permissions = path.stat().st_mode
    return _WORKING_FILE_MODE if permissions & _MODE_EXECUTABLE_BIT else _WORKING_FILE_MODE_NON_EXECUTABLE


def _run_git_command(
    repository: Repo,
    arguments: Sequence[str],
    *,
    payload: bytes | None = None,
    environment: Mapping[str, str] | None = None,
) -> str:
    """Execute Git with one optional input stream and child-only environment."""
    execute = cast(Callable[..., object], repository.git.execute)
    command = [GIT_EXECUTABLE, *arguments]
    options = {_GIT_ENV_OPTION: dict(environment)} if environment is not None else {}
    if payload is None:
        return cast(str, execute(command, **options))
    with TemporaryFile() as stream:
        stream.write(payload)
        stream.seek(0)
        return cast(str, execute(command, istream=stream, **options))


def _snapshot_template_contents(
    files: tuple[PlannedTemplateFile, ...],
    held_targets: set[Path],
    *,
    home: Path,
) -> dict[Path, bytes | None]:
    contents: dict[Path, bytes | None] = {}
    for file in files:
        target = file.target
        if target in held_targets:
            continue
        relative = target.relative_to(home)
        contents[relative] = target.read_bytes() if target.exists() else None
    return contents


def _require_commit_gate(repository: Repo, hook_outcomes: Mapping[str, HookConvergenceOutcome]) -> None:
    """Refuse when GitPython cannot execute the installed pre-commit hook."""
    outcome = hook_outcomes.get(_PRE_COMMIT_HOOK_NAME)
    if outcome not in (
        HookConvergenceOutcome.WRITTEN,
        HookConvergenceOutcome.UNCHANGED,
    ):
        label = outcome.value if outcome is not None else _MISSING_HOOK_OUTCOME
        raise _CommitGateUnavailable(_GATE_INSTALLATION_FAILED.format(outcome=label))
    try:
        hook_path = Path(
            _run_git_command(
                repository, (_GIT_REV_PARSE_COMMAND, _GIT_PATH_OPTION, _PRE_COMMIT_HOOK_RELATIVE_PATH)
            ).strip()
        )
        if not hook_path.is_absolute():
            hook_path = Path(repository.working_tree_dir or repository.git_dir) / hook_path
        gitpython_hook = Path(repository.git_dir) / _GITPYTHON_HOOKS_DIRECTORY / _PRE_COMMIT_HOOK_NAME
        if hook_path.resolve() != gitpython_hook.resolve():
            raise _CommitGateUnavailable(_GATE_HOOK_PATH_MISMATCH)
        if not gitpython_hook.is_file():
            raise _CommitGateUnavailable(_GATE_HOOK_MISSING)
        if not os.access(gitpython_hook, os.X_OK):
            raise _CommitGateUnavailable(_GATE_HOOK_NOT_EXECUTABLE)
    except (GitCommandError, OSError) as error:
        raise _CommitGateUnavailable(_GATE_VERIFICATION_FAILED.format(error=error)) from error


def _commit_candidates(repository: Repo, paths: tuple[Path, ...]) -> None:
    previous_head = _head_revision(repository)
    with TemporaryDirectory(dir=repository.git_dir, prefix=_TEMPORARY_INDEX_DIRECTORY_PREFIX) as directory:
        index_path = Path(directory) / _TEMPORARY_INDEX_FILENAME
        environment = no_autostash_env()
        environment[_TEMPORARY_INDEX_ENVIRONMENT_VARIABLE] = os.fspath(index_path)
        read_tree_arguments = (
            (_GIT_READ_TREE_COMMAND, _GIT_HEAD_REVISION)
            if previous_head is not None
            else (_GIT_READ_TREE_COMMAND, _GIT_EMPTY_TREE_OPTION)
        )
        _run_git_command(repository, read_tree_arguments, environment=environment)
        pathspecs = tuple(_GIT_LITERAL_PATHSPEC_PREFIX + path.as_posix() for path in paths)
        _run_git_command(
            repository,
            (_GIT_ADD_COMMAND, _GIT_FORCE_OPTION, _GIT_SEPARATOR, *pathspecs),
            environment=environment,
        )
        temporary_index = IndexFile(repository, index_path)
        # Snapshot hooks may mutate the temporary on-disk index; write_tree uses these cached candidate entries.
        indexed_paths = {os.fsdecode(entry.path) for entry in temporary_index.entries.values()}
        if not {path.as_posix() for path in paths}.issubset(indexed_paths):
            raise RuntimeError(_TEMPORARY_INDEX_CANDIDATES_MISSING_ERROR)
        try:
            commit = temporary_index.commit(
                _ACTIVATION_COMMIT_MESSAGE,
                author=Actor(_INSTALLATION_IDENTITY_NAME, _INSTALLATION_IDENTITY_EMAIL),
                committer=Actor(_INSTALLATION_IDENTITY_NAME, _INSTALLATION_IDENTITY_EMAIL),
            )
        except HookExecutionError as error:
            if Path(error.command[0]).name == _POST_COMMIT_HOOK_NAME and _head_revision(repository) != previous_head:
                _synchronize_candidate_index(repository, _head_revision(repository), paths)
            raise
        _synchronize_candidate_index(repository, commit.hexsha, paths)


def _head_revision(repository: Repo) -> str | None:
    return repository.head.commit.hexsha if repository.head.is_valid() else None


def _synchronize_candidate_index(repository: Repo, revision: str | None, paths: tuple[Path, ...]) -> None:
    if revision is None:
        raise RuntimeError(_COMMITTED_REVISION_MISSING_ERROR)
    pathspecs = tuple(_GIT_LITERAL_PATHSPEC_PREFIX + path.as_posix() for path in paths)
    output = _run_git_command(
        repository,
        (
            _GIT_LS_TREE_COMMAND,
            _LS_TREE_RECURSIVE_OPTION,
            _LS_FILES_NUL_OPTION,
            revision,
            _GIT_SEPARATOR,
            *pathspecs,
        ),
    )
    entries: dict[Path, tuple[str, str]] = {}
    for entry in _parse_tree_entries(output):
        if entry.kind != _GIT_BLOB_KIND:
            raise RuntimeError(_CANDIDATE_TREE_ENTRY_INVALID_ERROR)
        entries[entry.path] = (entry.mode, entry.object_id)
    if entries.keys() != set(paths):
        raise RuntimeError(_CANDIDATE_TREE_PATHS_MISMATCH_ERROR)
    records = tuple(
        _INDEX_INFO_RECORD.format(mode=mode, object_id=object_id, stage=_INDEX_STAGE_ZERO, tab=_TAB).encode(_ASCII)
        + os.fsencode(path.as_posix())
        + _NUL_BYTES
        for path, (mode, object_id) in sorted(entries.items())
    )
    _run_index_update(repository, (_GIT_NUL_FLAG, _GIT_INDEX_INFO_FLAG), _EMPTY_BYTES.join(records))


def _restore_written_templates(
    paths: tuple[Path, ...],
    plan: TemplateInstallationPlan,
    prior_contents: Mapping[Path, bytes | None],
    *,
    home: Path,
) -> tuple[Path, ...]:
    expected_contents = {
        file.target.relative_to(home): file.content for target in plan.targets for file in target.files
    }
    unrestored: list[Path] = []
    for relative in paths:
        target = home / relative
        try:
            if target.is_symlink() or not target.is_file():
                unrestored.append(relative)
                continue
            if target.read_bytes() != expected_contents[relative]:
                unrestored.append(relative)
                continue
            previous = prior_contents[relative]
            if previous is None:
                target.unlink()
            else:
                target.write_bytes(previous)
        except OSError:
            unrestored.append(relative)
    return tuple(unrestored)


def _run_index_update(repository: Repo, arguments: Sequence[str], payload: bytes) -> None:
    """Feed a NUL-delimited index operation through a file-backed GitPython stream."""
    _run_git_command(
        repository,
        (_GIT_LITERAL_PATHSPECS_ARGUMENT, _GIT_UPDATE_INDEX_COMMAND, *arguments),
        payload=payload,
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
    return tuple((entry.path, entry.mode) for entry in _parse_tree_entries(tree))


def _parse_tree_entries(tree: str) -> tuple[_TreeGitEntry, ...]:
    """Parse Git's NUL-delimited ls-tree records once for all tree readers."""
    entries: list[_TreeGitEntry] = []
    for entry in tree.split(_NUL):
        if not entry:
            continue
        metadata, raw_path = entry.split(_TAB, maxsplit=1)
        mode, kind, object_id = metadata.split(_GIT_TREE_METADATA_SEPARATOR, maxsplit=2)
        entries.append(_TreeGitEntry(Path(raw_path), mode, kind, object_id))
    return tuple(entries)


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
            _TEMPLATES_HELD_FIELD: _count_disposition(outcomes, HomeTemplateDisposition.HELD),
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
