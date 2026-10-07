"""Decision owner for converging the DeepSeek runtime, its TUI and every plugin.

One entry decides the whole sequence: refuse while another run holds the stack, choose the
newest set where everything fits, snapshot, apply, verify, and keep the applied set or
restore the snapshot. Callers never sequence those steps; the effects only execute them.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from instrukt_ai_logging import get_logger

from teleclaude.core.reconciliation.deepseek_fit import (
    RUNTIME_PACKAGE,
    Adoption,
    Advisory,
    Blocker,
    CompatibilityView,
    DeepSeekStackError,
    PlannedPackage,
    RequiredPlugin,
    Stack,
    select_adoption,
)

logger = get_logger(__name__)

_LOG_OUTCOME = "DeepSeek stack convergence finished"
_LOG_SELECTED = "DeepSeek stack convergence selected a set"
_LOG_FAILED = "DeepSeek stack convergence failed after the snapshot"
_LOG_INTERRUPTED = "DeepSeek stack convergence was interrupted after the snapshot; the restore is incomplete"
_INTERRUPTED_DETAIL_TEMPLATE = "The run was interrupted after the first change: {error}"


class StackOutcome(StrEnum):
    """How one convergence run ended."""

    UPGRADED = "upgraded"
    UNCHANGED = "unchanged"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_INCOMPLETE = "rollback_incomplete"


class UnchangedReason(StrEnum):
    """Why a run changed nothing."""

    NO_FITTING_SET = "no_fitting_set"
    RUN_IN_PROGRESS = "run_in_progress"


class ConvergenceStep(StrEnum):
    """The steps after the snapshot that can fail or differ."""

    RUNTIME_INSTALL = "runtime_install"
    PROFILE_APPLY = "profile_apply"
    GATE = "gate"
    RUNTIME_RESTORE = "runtime_restore"
    PROFILE_RESTORE = "profile_restore"


class GateCheck(StrEnum):
    """The checks of the verification gate, in the order the gate runs them."""

    COMPOSED_CONFIG = "composed_config"
    PROFILE_START = "profile_start"
    COMPOSER_READY = "composer_ready"
    TURN = "turn"
    HOOK_CONTEXT_TURN = "hook_context_turn"


@dataclass(frozen=True)
class GateVerdict:
    """What the verification gate concluded; ``failed_check`` names the check that failed."""

    passed: bool
    failed_check: GateCheck | None
    detail: str | None


@dataclass(frozen=True)
class SnapshotRef:
    """A taken snapshot: where it is kept and the runtime version it recorded."""

    location: str
    runtime_version: str | None


@dataclass(frozen=True)
class PackageChange:
    """One package's move: ``profile`` is ``None`` for the runtime, versions are ``None`` when absent."""

    profile: str | None
    name: str
    previous: str | None
    adopted: str | None


@dataclass(frozen=True)
class StackDifference:
    """One part of the stack that still differs from the snapshot after a restore."""

    step: ConvergenceStep
    subject: str
    detail: str | None


@dataclass(frozen=True)
class ConvergenceResult:
    """The published outcome of one convergence run."""

    outcome: StackOutcome
    unchanged_reason: UnchangedReason | None
    changes: tuple[PackageChange, ...]
    blockers: tuple[Blocker, ...]
    advisories: tuple[Advisory, ...]
    failed_step: ConvergenceStep | None
    failed_check: GateCheck | None
    failure_detail: str | None
    differences: tuple[StackDifference, ...]
    retained_snapshot: str | None


class DeepSeekStackEffects(Protocol):
    """The reads and writes the convergence decision drives; none of them decides anything.

    Every effect reports its own failure as ``DeepSeekStackError``; ``restore`` instead
    returns each part it could not restore.
    """

    def acquire_run(self) -> AbstractContextManager[bool]:
        """Hold the run lock for the harness home; yields ``False`` when another run holds it."""
        ...

    def read_stack(self, required: Sequence[RequiredPlugin]) -> Stack: ...

    def compatibility_view(self) -> CompatibilityView: ...

    def take_snapshot(self, stack: Stack) -> SnapshotRef: ...

    def install_runtime(self, version: str) -> None: ...

    def apply_profile(self, profile: str, packages: tuple[PlannedPackage, ...]) -> None: ...

    def restore(self, snapshot: SnapshotRef) -> tuple[StackDifference, ...]: ...

    def release_snapshot(self, snapshot: SnapshotRef) -> None: ...

    def run_gate(self, stack: Stack) -> GateVerdict: ...


def converge_deepseek_stack(effects: DeepSeekStackEffects, required: Sequence[RequiredPlugin]) -> ConvergenceResult:
    """Move the stack to the newest set where everything fits, verified, or leave it as it was."""
    with effects.acquire_run() as acquired:
        if not acquired:
            return _logged(_unchanged(UnchangedReason.RUN_IN_PROGRESS))
        stack = effects.read_stack(required)
        selection = select_adoption(stack, effects.compatibility_view())
        if isinstance(selection, tuple):
            logger.info(_LOG_SELECTED, selected=None, blockers=len(selection))
            return _logged(_unchanged(UnchangedReason.NO_FITTING_SET, blockers=selection))
        logger.info(_LOG_SELECTED, selected=selection.runtime_version, blockers=len(selection.rejected))
        if selection.is_current:
            return _logged(
                _unchanged(UnchangedReason.NO_FITTING_SET, blockers=selection.rejected, advisories=selection.advisories)
            )
        return _logged(_apply_and_verify(effects, required, stack, selection))


def _apply_and_verify(
    effects: DeepSeekStackEffects,
    required: Sequence[RequiredPlugin],
    stack: Stack,
    adoption: Adoption,
) -> ConvergenceResult:
    snapshot = effects.take_snapshot(stack)
    try:
        failure = _apply(effects, adoption)
        if failure is None:
            failure = _verify(effects, required)
    except BaseException as error:
        # An unplanned error or an interrupt after the first change must not leave the machine between two sets.
        differences = effects.restore(snapshot)
        if not differences:
            effects.release_snapshot(snapshot)
            raise
        logger.error(_LOG_INTERRUPTED, differences=len(differences), snapshot=snapshot.location)
        return ConvergenceResult(
            StackOutcome.ROLLBACK_INCOMPLETE,
            None,
            (),
            adoption.rejected,
            adoption.advisories,
            None,
            None,
            _INTERRUPTED_DETAIL_TEMPLATE.format(error=repr(error)),
            differences,
            snapshot.location,
        )
    if failure is None:
        effects.release_snapshot(snapshot)
        return ConvergenceResult(
            StackOutcome.UPGRADED,
            None,
            _changes(adoption),
            adoption.rejected,
            adoption.advisories,
            None,
            None,
            None,
            (),
            None,
        )
    logger.warning(
        _LOG_FAILED,
        step=failure.step,
        check=failure.check,
        detail=failure.detail,
    )
    differences = effects.restore(snapshot)
    if not differences:
        effects.release_snapshot(snapshot)
    return ConvergenceResult(
        StackOutcome.ROLLBACK_INCOMPLETE if differences else StackOutcome.ROLLED_BACK,
        None,
        (),
        adoption.rejected,
        adoption.advisories,
        failure.step,
        failure.check,
        failure.detail,
        differences,
        snapshot.location if differences else None,
    )


@dataclass(frozen=True)
class _Failure:
    step: ConvergenceStep
    check: GateCheck | None
    detail: str | None


def _apply(effects: DeepSeekStackEffects, adoption: Adoption) -> _Failure | None:
    """Install the runtime when it moves, then add each profile's packages; the runtime goes first because
    the plugin manager judges compatibility against the installed runtime."""
    if adoption.moves_runtime:
        try:
            effects.install_runtime(adoption.runtime_version)
        except DeepSeekStackError as error:
            return _Failure(ConvergenceStep.RUNTIME_INSTALL, None, str(error))
    for profile, packages in adoption.profiles.items():
        if not packages:
            continue
        try:
            effects.apply_profile(profile, packages)
        except DeepSeekStackError as error:
            return _Failure(ConvergenceStep.PROFILE_APPLY, None, str(error))
    return None


def _verify(effects: DeepSeekStackEffects, required: Sequence[RequiredPlugin]) -> _Failure | None:
    """Run the verification gate against the stack as it now stands."""
    try:
        verdict = effects.run_gate(effects.read_stack(required))
    except DeepSeekStackError as error:
        return _Failure(ConvergenceStep.GATE, None, str(error))
    if verdict.passed:
        return None
    return _Failure(ConvergenceStep.GATE, verdict.failed_check, verdict.detail)


def _changes(adoption: Adoption) -> tuple[PackageChange, ...]:
    changes: list[PackageChange] = []
    if adoption.moves_runtime:
        changes.append(
            PackageChange(None, RUNTIME_PACKAGE, adoption.previous_runtime_version, adoption.runtime_version)
        )
    for profile, packages in adoption.profiles.items():
        changes.extend(
            PackageChange(profile, package.name, package.previous_version, package.adopted_version or package.reference)
            for package in packages
        )
    return tuple(changes)


def _unchanged(
    reason: UnchangedReason,
    blockers: tuple[Blocker, ...] = (),
    advisories: tuple[Advisory, ...] = (),
) -> ConvergenceResult:
    return ConvergenceResult(StackOutcome.UNCHANGED, reason, (), blockers, advisories, None, None, None, (), None)


def _logged(result: ConvergenceResult) -> ConvergenceResult:
    logger.info(
        _LOG_OUTCOME,
        outcome=result.outcome,
        reason=result.unchanged_reason,
        changes=len(result.changes),
        blockers=len(result.blockers),
        advisories=len(result.advisories),
        differences=len(result.differences),
    )
    return result
