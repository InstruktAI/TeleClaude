"""Current-baseline Blueprint queries that observe workflow-owned maintenance."""

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
from teleclaude.core.blueprint.manifest import read_published_generation
from teleclaude.core.integration.post_commit_maintenance import (
    ON_DEMAND_MAINTENANCE_COMMAND,
    MaintenanceObservationState,
    observe_maintenance_action,
    selected_maintenance_revision,
)
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.git import BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError

_OBSERVATION_BUDGET_SECONDS = 30.0
_OBSERVATION_POLL_INTERVAL_SECONDS = 0.1
_MAINTENANCE_OBSERVATION_FAILED_EVENT = "blueprint_maintenance_observation_failed"
_MAINTENANCE_OBSERVATION_UNAVAILABLE_REASON = "Blueprint maintenance state could not be observed"
_MAINTENANCE_FAILED_REASON = "Blueprint maintenance failed before publishing a current generation"
_MAINTENANCE_NOT_RECORDED_REASON = "Blueprint maintenance was not recorded for the selected committed source"
_MAINTENANCE_OBSERVATION_EXPIRED_REASON = "Blueprint maintenance did not converge within the observation bound"
_MAIN_REVISION_UNRESOLVED_REASON = "The selected committed source could not be resolved"
_MAIN_REVISION_RECHECK_FAILED_REASON = (
    "The selected committed source could not be rechecked after reading the Blueprint"
)
_GENERATION_MALFORMED_REASON = "The current Blueprint generation is malformed or incomplete"
_GENERATION_ABSENT_REASON = "No complete Blueprint generation is published"
_GENERATION_STALE_REASON = "The published Blueprint does not match the selected committed source"

logger = get_logger(__name__)


class BlueprintQueryState(StrEnum):
    """Whether one complete generation matching canonical main was established."""

    FRESH = "fresh"
    FAILED = "failed"
    ABSENT = "absent"
    EXPIRED = "expired"
    MAIN_UNRESOLVED = "main_unresolved"
    MALFORMED = "malformed"


@dataclass(frozen=True)
class BlueprintQueryResult:
    """A pinned current generation or explicit unavailability with its recovery path."""

    state: BlueprintQueryState
    current_main_sha: str | None
    generation: PinnedBlueprintGeneration | None = None
    reason: str = ""
    recovery_reference: str | None = None
    maintenance_state: MaintenanceObservationState | None = None


def query_current_blueprint(project_root: str | Path) -> BlueprintQueryResult:
    """Return a complete generation for committed main or wait briefly for its owner."""
    root = resolve_project_state_root(project_root)
    deadline = time.monotonic() + _OBSERVATION_BUDGET_SECONDS
    last_maintenance_state: MaintenanceObservationState | None = None

    while True:
        current = _fresh_generation(root)
        if current.state is BlueprintQueryState.FRESH:
            return current
        if current.state is BlueprintQueryState.MAIN_UNRESOLVED:
            return current

        try:
            observation = observe_maintenance_action(root, BLUEPRINT_MAINTENANCE_ACTION_ID)
        except (OSError, ValueError, GitCommandError, InvalidGitRepositoryError, NoSuchPathError):
            logger.warning(_MAINTENANCE_OBSERVATION_FAILED_EVENT, exc_info=True)
            return BlueprintQueryResult(
                state=BlueprintQueryState.MALFORMED,
                current_main_sha=current.current_main_sha,
                reason=_MAINTENANCE_OBSERVATION_UNAVAILABLE_REASON,
                recovery_reference=ON_DEMAND_MAINTENANCE_COMMAND,
            )
        last_maintenance_state = observation.state
        if observation.state is MaintenanceObservationState.FAILED:
            current = _fresh_generation(root)
            if current.state is BlueprintQueryState.FRESH:
                return current
            return BlueprintQueryResult(
                state=BlueprintQueryState.FAILED,
                current_main_sha=current.current_main_sha,
                reason=_MAINTENANCE_FAILED_REASON,
                recovery_reference=observation.recovery_reference,
                maintenance_state=observation.state,
            )
        if observation.state is MaintenanceObservationState.ABSENT:
            current = _fresh_generation(root)
            if current.state is BlueprintQueryState.FRESH:
                return current
            return BlueprintQueryResult(
                state=(
                    BlueprintQueryState.MALFORMED
                    if current.state is BlueprintQueryState.MALFORMED
                    else BlueprintQueryState.ABSENT
                ),
                current_main_sha=current.current_main_sha,
                reason=current.reason or _MAINTENANCE_NOT_RECORDED_REASON,
                recovery_reference=ON_DEMAND_MAINTENANCE_COMMAND,
                maintenance_state=observation.state,
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            current = _fresh_generation(root)
            if current.state is BlueprintQueryState.FRESH:
                return current
            return BlueprintQueryResult(
                state=(
                    BlueprintQueryState.MALFORMED
                    if current.state is BlueprintQueryState.MALFORMED
                    else BlueprintQueryState.EXPIRED
                ),
                current_main_sha=current.current_main_sha,
                reason=current.reason or _MAINTENANCE_OBSERVATION_EXPIRED_REASON,
                recovery_reference=ON_DEMAND_MAINTENANCE_COMMAND,
                maintenance_state=last_maintenance_state,
            )
        time.sleep(min(_OBSERVATION_POLL_INTERVAL_SECONDS, remaining))


def _fresh_generation(root: Path) -> BlueprintQueryResult:
    """Pin a generation and verify main did not advance across its freshness observation."""
    try:
        observed_main_sha = selected_maintenance_revision(root)
    except (OSError, ValueError, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, BadName):
        return BlueprintQueryResult(
            state=BlueprintQueryState.MAIN_UNRESOLVED,
            current_main_sha=None,
            reason=_MAIN_REVISION_UNRESOLVED_REASON,
            recovery_reference=ON_DEMAND_MAINTENANCE_COMMAND,
        )

    published = read_published_generation(root)
    if published is None:
        pointer = current_generation_pointer(root)
        return BlueprintQueryResult(
            state=(BlueprintQueryState.MALFORMED if pointer.is_symlink() else BlueprintQueryState.ABSENT),
            current_main_sha=observed_main_sha,
            reason=(_GENERATION_MALFORMED_REASON if pointer.is_symlink() else _GENERATION_ABSENT_REASON),
        )

    generation, manifest = published
    try:
        latest_main_sha = selected_maintenance_revision(root)
    except (OSError, ValueError, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, BadName):
        return BlueprintQueryResult(
            state=BlueprintQueryState.MAIN_UNRESOLVED,
            current_main_sha=None,
            reason=_MAIN_REVISION_RECHECK_FAILED_REASON,
            recovery_reference=ON_DEMAND_MAINTENANCE_COMMAND,
        )
    if latest_main_sha != observed_main_sha or manifest.baseline_sha != latest_main_sha:
        return BlueprintQueryResult(
            state=BlueprintQueryState.ABSENT,
            current_main_sha=latest_main_sha,
            reason=_GENERATION_STALE_REASON,
        )
    return BlueprintQueryResult(
        state=BlueprintQueryState.FRESH,
        current_main_sha=latest_main_sha,
        generation=generation,
    )
