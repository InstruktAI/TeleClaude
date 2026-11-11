"""Blueprint queries: answer from the published generation and name how the asking checkout differs from it.

The query reports facts: which revision the generation describes, which baseline maintenance converges
to, what maintenance is doing, and which files the asking checkout holds differently. Whether any of
that matters to the question being asked is the caller's judgment.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import BLUEPRINT_MAINTENANCE_ACTION_ID
from teleclaude.core.blueprint._paths import (
    PinnedBlueprintGeneration,
    current_generation_pointer,
)
from teleclaude.core.blueprint.manifest import BlueprintManifest, read_published_generation
from teleclaude.core.integration.post_commit_maintenance import (
    ON_DEMAND_MAINTENANCE_COMMAND,
    MaintenanceObservationState,
    SelectedBaseline,
    observe_maintenance_action,
    selected_maintenance_baseline,
)
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.git import BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

_OBSERVATION_BUDGET_SECONDS = 30.0
_OBSERVATION_POLL_INTERVAL_SECONDS = 0.1
_MAINTENANCE_OBSERVATION_FAILED_EVENT = "blueprint_maintenance_observation_failed"
_MAINTENANCE_OBSERVATION_UNAVAILABLE_REASON = "Blueprint maintenance state could not be observed"
_MAINTENANCE_FAILED_REASON = "Blueprint maintenance failed before publishing a complete generation"
_MAINTENANCE_NOT_RECORDED_REASON = "Blueprint maintenance was not recorded and no complete generation is published"
_MAINTENANCE_OBSERVATION_EXPIRED_REASON = "Blueprint maintenance did not converge within the observation bound"
_GENERATION_MALFORMED_REASON = "The current Blueprint generation is malformed or incomplete"
_GIT_DIFF_NAME_ONLY = "--name-only"
_GIT_NO_RENAMES = "--no-renames"
_GIT_NUL_SEPARATED = "-z"
_GIT_LS_FILES_OTHERS = "--others"
_GIT_EXCLUDE_STANDARD = "--exclude-standard"
_GIT_HEAD_REFERENCE = "HEAD"
_NUL = "\0"
_GIT_FAILURES = (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, BadName, OSError, ValueError)

logger = get_logger(__name__)


class BlueprintQueryState(StrEnum):
    """Whether the query answered from a complete published generation, and why not when it did not."""

    ANSWERED = "answered"
    FAILED = "failed"
    ABSENT = "absent"
    EXPIRED = "expired"
    MALFORMED = "malformed"
    REVISION_MISSING = "revision_missing"


@dataclass(frozen=True)
class BlueprintQueryResult:
    """A pinned complete generation with the facts that locate it, or explicit unavailability with its recovery path.

    ``differing_files`` are the files in which the asking checkout's working tree (tracked changes and
    untracked files) differs from the generation revision; ``difference_error`` is set instead when that
    difference could not be computed, and ``baseline_error`` when the baseline could not be resolved.
    """

    state: BlueprintQueryState
    generation: PinnedBlueprintGeneration | None = None
    manifest: BlueprintManifest | None = None
    baseline: SelectedBaseline | None = None
    baseline_error: str | None = None
    maintenance_state: MaintenanceObservationState | None = None
    asking_head: str | None = None
    differing_files: tuple[str, ...] = ()
    difference_error: str | None = None
    reason: str = ""
    recovery_reference: str | None = None


def query_current_blueprint(
    project_root: str | Path, asking_checkout: str | Path | None = None
) -> BlueprintQueryResult:
    """Answer from the published generation, or wait briefly for the owner when none is complete yet.

    The generation is read from the project's shared state; the difference is computed for
    ``asking_checkout``, which defaults to the project root.
    """
    root = resolve_project_state_root(project_root)
    asking = Path(asking_checkout) if asking_checkout is not None else root
    deadline = time.monotonic() + _OBSERVATION_BUDGET_SECONDS
    last_maintenance_state: MaintenanceObservationState | None = None

    while True:
        published = read_published_generation(root)
        if published is not None:
            return _answer(root, asking, *published)

        try:
            observation = observe_maintenance_action(root, BLUEPRINT_MAINTENANCE_ACTION_ID)
        except (OSError, ValueError, GitCommandError, InvalidGitRepositoryError, NoSuchPathError):
            logger.warning(_MAINTENANCE_OBSERVATION_FAILED_EVENT, exc_info=True)
            return BlueprintQueryResult(
                state=BlueprintQueryState.MALFORMED,
                reason=_MAINTENANCE_OBSERVATION_UNAVAILABLE_REASON,
                recovery_reference=ON_DEMAND_MAINTENANCE_COMMAND,
            )
        # Maintenance can publish its generation and settle its record between the read above and this
        # observation, so a terminal observation never stands without pinning the pointer once more.
        published = read_published_generation(root)
        if published is not None:
            return _answer(root, asking, *published)
        pointer_is_malformed = current_generation_pointer(root).is_symlink()
        last_maintenance_state = observation.state
        if observation.state is MaintenanceObservationState.FAILED:
            return BlueprintQueryResult(
                state=BlueprintQueryState.FAILED,
                reason=_MAINTENANCE_FAILED_REASON,
                recovery_reference=observation.recovery_reference,
                maintenance_state=observation.state,
            )
        if observation.state is MaintenanceObservationState.ABSENT:
            return BlueprintQueryResult(
                state=BlueprintQueryState.MALFORMED if pointer_is_malformed else BlueprintQueryState.ABSENT,
                reason=_GENERATION_MALFORMED_REASON if pointer_is_malformed else _MAINTENANCE_NOT_RECORDED_REASON,
                recovery_reference=ON_DEMAND_MAINTENANCE_COMMAND,
                maintenance_state=observation.state,
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return BlueprintQueryResult(
                state=BlueprintQueryState.MALFORMED if pointer_is_malformed else BlueprintQueryState.EXPIRED,
                reason=_GENERATION_MALFORMED_REASON
                if pointer_is_malformed
                else _MAINTENANCE_OBSERVATION_EXPIRED_REASON,
                recovery_reference=ON_DEMAND_MAINTENANCE_COMMAND,
                maintenance_state=last_maintenance_state,
            )
        time.sleep(min(_OBSERVATION_POLL_INTERVAL_SECONDS, remaining))


def _answer(
    root: Path, asking: Path, generation: PinnedBlueprintGeneration, manifest: BlueprintManifest
) -> BlueprintQueryResult:
    """The pinned generation with its baseline, maintenance state and the asking checkout's difference."""
    try:
        Repo(str(root)).commit(manifest.baseline_sha)
    except _GIT_FAILURES:
        return BlueprintQueryResult(
            state=BlueprintQueryState.REVISION_MISSING,
            generation=generation,
            manifest=manifest,
            reason=f"The published Blueprint describes revision {manifest.baseline_sha}, which this repository does not hold",
            recovery_reference=ON_DEMAND_MAINTENANCE_COMMAND,
        )

    baseline: SelectedBaseline | None = None
    baseline_error: str | None = None
    try:
        baseline = selected_maintenance_baseline(root)
    except _GIT_FAILURES as exc:
        logger.warning("blueprint_baseline_unresolved", exc_info=True)
        baseline_error = str(exc)

    maintenance_state: MaintenanceObservationState | None = None
    recovery_reference: str | None = None
    try:
        observation = observe_maintenance_action(root, BLUEPRINT_MAINTENANCE_ACTION_ID)
        maintenance_state = observation.state
        recovery_reference = observation.recovery_reference
    except (OSError, ValueError, GitCommandError, InvalidGitRepositoryError, NoSuchPathError):
        logger.warning(_MAINTENANCE_OBSERVATION_FAILED_EVENT, exc_info=True)

    asking_head: str | None = None
    differing_files: tuple[str, ...] = ()
    difference_error: str | None = None
    try:
        asking_repository = Repo(str(asking))
        asking_head = asking_repository.commit(_GIT_HEAD_REFERENCE).hexsha
        differing_files = _differing_files(asking_repository, manifest.baseline_sha)
    except _GIT_FAILURES as exc:
        logger.warning("blueprint_difference_uncomputed", asking_checkout=str(asking), exc_info=True)
        difference_error = str(exc)

    return BlueprintQueryResult(
        state=BlueprintQueryState.ANSWERED,
        generation=generation,
        manifest=manifest,
        baseline=baseline,
        baseline_error=baseline_error,
        maintenance_state=maintenance_state,
        asking_head=asking_head,
        differing_files=differing_files,
        difference_error=difference_error,
        recovery_reference=recovery_reference,
    )


def _differing_files(repository: Repo, revision: str) -> tuple[str, ...]:
    """Files whose working-tree content differs from ``revision``: tracked changes plus untracked files."""
    tracked = str(repository.git.diff(_GIT_DIFF_NAME_ONLY, _GIT_NO_RENAMES, _GIT_NUL_SEPARATED, revision))
    untracked = str(repository.git.ls_files(_GIT_LS_FILES_OTHERS, _GIT_EXCLUDE_STANDARD, _GIT_NUL_SEPARATED))
    return tuple(sorted({path for path in (*tracked.split(_NUL), *untracked.split(_NUL)) if path}))
