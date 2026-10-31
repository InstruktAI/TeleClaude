"""The install act: the one path by which a revision becomes the platform's active release.

The bootstrap, the channel reaction, ``telec app install`` and the move off a project checkout all call
``install``. It refuses a target older than the active release, prepares the release while the daemon
serves, stops the daemon through its lifecycle, runs the release's migrations in the stopped window,
switches ``current``, starts and verifies the new revision, records the outcome, moves every running
terminal interface onto it and prunes releases older than the previous that no running terminal interface
still holds. The store owners' start signals alone decide how a failure recovers: before any
migration started the previously active release is returned to service; after one started the daemon
stays stopped and the failure is repaired forward
(``local/projects/teleclaude/spec/feature/reconciliation/installed-releases``).

Everything that touches git, processes or the filesystem is a port the act drives; the act decides.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from instrukt_ai_logging import get_logger
from pydantic import ValidationError

from teleclaude.core.integration.daemon_window import ADMISSION_WAIT_BOUND_SECONDS
from teleclaude.core.reconciliation.installation import (
    ActOutcome,
    InstallAct,
    InstallationLayout,
    InstallRecord,
    MigratedState,
    RollbackRefusal,
    leave_unrecorded_start,
    read_record,
    update_record,
)
from teleclaude.core.reconciliation.installation_release import ReleasePreparationError
from teleclaude.core.reconciliation.release_transition import Refusal, TransitionRefusal

logger = get_logger(__name__)

_DECISION_EVENT = "install_act_decision"
_PUBLICATION_EVENT = "install_act_publication_failed"
_UNACCOUNTED_NOT_PERSISTED_EVENT = "install_act_outcome_not_persisted"
_TUI_RELOAD_FAILED_EVENT = "install_act_tui_reload_failed"
_TUI_REGISTRY_UNREADABLE_EVENT = "install_act_tui_registry_unreadable"
_TUI_HOLD_UNKNOWN_EVENT = "install_act_prune_skipped_tui_hold_unknown"
_STOP_WITHHELD = "the daemon's stop was withheld: {detail}"
_MIGRATION_FAILED = "the release's migrations failed: {detail}"
_START_UNVERIFIED = "the daemon did not verify on revision {revision}: {detail}"
_NOT_SETTLED = "; the attempted release could not be stopped, so nothing was switched back: {detail}"
_SETTLE_BOUND_EXPIRED = "; the bound of {seconds:g}s for the attempted release to become stoppable expired"
_SETTLE_POLL_SECONDS = 1.0
_RESTORE_UNVERIFIED = "; the previously active release did not verify either: {detail}"
_PREPARATION_FAILED = "preparing the release failed at {step}: {detail}"
_IN_PROGRESS = "another install or rollback is in progress"
_SUPERSEDED = (
    "revision {target} was overtaken by a newer green revision before its activation, so the active release is kept"
)
_MIGRATIONS_STARTED = "a migration started since the active release became active, in {stores}"
_NO_PREVIOUS = "no previous release is installed"
_INSTALL_UNSETTLED = (
    "an install of {target} ended without settling, so what it changed cannot be ruled out and rollback "
    "is not offered over it; run `telec app install` to complete it"
)
_PREVIOUS_GONE = "the previous release folder {revision} is gone"
_NO_REVISION = "none"
_STORE_SEPARATOR = ", "
_UNKNOWN_STORES = "a store that could not be named"


class InstallStatus(StrEnum):
    """How an act ended, for the caller that asked for it."""

    COMPLETED = "completed"
    UNCHANGED = "unchanged"
    REFUSED = "refused"
    FAILED = "failed"


@dataclass(frozen=True)
class InstallResult:
    """The outcome of one act: what ended it and, after a failure that left the daemon stopped, what it reached."""

    status: InstallStatus
    revision: str | None
    reason: str | None = None
    reached_stores: tuple[str, ...] = ()
    left_stopped: bool = False
    publication_failure: str | None = None
    contained: bool = False
    superseded: bool = False


@dataclass(frozen=True)
class InstallRequest:
    """What one install asks for.

    ``target`` is a full commit or a reference the kept repository resolves; ``release_tag`` names the
    published release it was selected as, which adds the version half of the forward rule. ``source`` is
    the repository to keep when the installation has none yet. ``checkout`` is a project checkout whose
    daemon serves the machine, for the move off it; ``running`` is the revision that checkout runs, which
    stands in for the active release when the forward rule and the migrations ask where the platform is.
    ``is_superseded`` is the caller's confirmation that a channel-resolved edge target is still the newest
    green revision: the act asks it with the resolved commit once the release is prepared and before anything
    stops, and ends refused when it answers yes.
    """

    target: str
    release_tag: str | None = None
    source: str | None = None
    checkout: Path | None = None
    running: str | None = None
    is_superseded: Callable[[str], bool] | None = None


@dataclass(frozen=True)
class StopVerdict:
    """Whether a serving daemon was stopped through its lifecycle, or why the stop was withheld."""

    stopped: bool
    reason: str | None = None


@dataclass(frozen=True)
class StepVerdict:
    """Whether one port step succeeded, and the reason when it did not."""

    succeeded: bool
    reason: str | None = None
    unaccounted: bool = False


class InstallPorts(Protocol):
    """The infrastructure one act drives; each port executes and decides nothing."""

    def exclusive(self) -> AbstractContextManager[None]:
        """Hold the installation against a second act; raises ``InstallInProgress`` when one is running."""
        ...

    def fetch(self, source: str | None) -> None:
        """Keep the repository of the source and bring it up to date."""
        ...

    def resolve(self, reference: str) -> str:
        """The full commit a reference names in the kept repository."""
        ...

    def refusal(self, active: str, target: str, release_tag: str | None) -> Refusal | None:
        """Why ``target`` is not an admitted forward step over ``active``."""
        ...

    def prepare(self, revision: str) -> None:
        """Add and build the release while the daemon serves."""
        ...

    def daemon_serving(self) -> bool:
        """Whether a daemon serves the machine."""
        ...

    def stop(self, checkout: Path | None) -> StopVerdict:
        """Stop the serving daemon through the active release's lifecycle, or the checkout's when none is active."""
        ...

    def migrate(self, previous: str | None, target: str) -> StepVerdict:
        """Run the target release's migrations and open its stores, in the stopped window."""
        ...

    def switch(self, revision: str | None) -> None:
        """Point ``current`` at the release of ``revision``; ``None`` withdraws the pointer."""
        ...

    def start_and_verify(self, revision: str | None, checkout: Path | None) -> StepVerdict:
        """Start through ``current`` (or the checkout's lifecycle) and verify the daemon serves ``revision``."""
        ...

    def ensure_stopped(self) -> StopVerdict:
        """Stop the daemon through ``current``'s lifecycle, answering whether the lifecycle recorded it stopped."""
        ...

    def publish_cli(self) -> None:
        """Publish the global ``telec`` through ``current``."""
        ...

    def reload_tuis(self) -> None:
        """Signal every running terminal interface to reload onto the installed code."""
        ...

    def held_tui_revisions(self) -> frozenset[str | None]:
        """The start revision each running terminal interface's record names; ``None`` stands for a record naming none."""
        ...

    def prune(self, keep: frozenset[str]) -> None:
        """Remove every release folder except the ones named."""
        ...

    def publish(self, revision: str) -> str | None:
        """Publish the release's documentation, agent artifacts and schemas, then converge the fleet's plumbing to its templates; the failure detail, or ``None``."""
        ...


class InstallInProgress(RuntimeError):
    """Another act holds the installation."""


def install(request: InstallRequest, ports: InstallPorts, layout: InstallationLayout | None = None) -> InstallResult:
    """Install the requested revision as the active release."""
    resolved = layout or InstallationLayout()
    try:
        with ports.exclusive():
            return _install(request, ports, resolved)
    except InstallInProgress:
        return InstallResult(status=InstallStatus.REFUSED, revision=None, reason=_IN_PROGRESS)


def _install(request: InstallRequest, ports: InstallPorts, layout: InstallationLayout) -> InstallResult:
    active = layout.active_revision()
    try:
        ports.fetch(request.source)
        target = ports.resolve(request.target)
    except ReleasePreparationError as error:
        return _ended(layout, ActOutcome.FAILED_RETURNED, request.target, _preparation_reason(error))
    if active == target:
        logger.info(_DECISION_EVENT, decision=InstallStatus.UNCHANGED, revision=target)
        return InstallResult(
            status=InstallStatus.UNCHANGED,
            revision=target,
            publication_failure=_replay_publication(target, ports, layout),
        )
    baseline = active or request.running
    if baseline is not None and baseline != target:
        refusal = ports.refusal(baseline, target, request.release_tag)
        if refusal is not None:
            logger.info(_DECISION_EVENT, decision=InstallStatus.REFUSED, revision=target, refusal=refusal.reason)
            ended = _ended(layout, ActOutcome.REFUSED, target, refusal.detail)
            return replace(ended, contained=refusal.reason is TransitionRefusal.OLDER)
    provisioning = active is None and not ports.daemon_serving()
    try:
        ports.prepare(target)
    except ReleasePreparationError as error:
        return _ended(layout, ActOutcome.FAILED_RETURNED, target, _preparation_reason(error))
    if request.is_superseded is not None:
        try:
            superseded = request.is_superseded(target)
        except ReleasePreparationError as error:
            return _ended(layout, ActOutcome.FAILED_RETURNED, target, _preparation_reason(error))
        if superseded:
            # Activation begins at the stop; until then an overtaken target costs nothing to abandon.
            return replace(
                _ended(layout, ActOutcome.REFUSED, target, _SUPERSEDED.format(target=target)), superseded=True
            )
    if provisioning:
        return _provision(target, request.running, ports, layout)
    return _replace(request, active, baseline, target, ports, layout)


def _provision(target: str, running: str | None, ports: InstallPorts, layout: InstallationLayout) -> InstallResult:
    """Initial provisioning: nothing is active and nothing serves, so there is nothing to stop or verify."""
    update_record(lambda record: record.installing_toward(target), layout)
    migration = ports.migrate(running, target)
    if not migration.succeeded:
        return _failed_after_window(
            layout, target, None, _MIGRATION_FAILED.format(detail=migration.reason), ports, None, migration.unaccounted
        )
    ports.switch(target)
    update_record(lambda record: record.activated(target), layout)
    ports.publish_cli()
    return _completed(layout, target, ports)


def _replace(
    request: InstallRequest,
    active: str | None,
    baseline: str | None,
    target: str,
    ports: InstallPorts,
    layout: InstallationLayout,
) -> InstallResult:
    """Replace the serving platform: stop, migrate in the window, switch, start and verify."""
    if ports.daemon_serving():
        stop = ports.stop(request.checkout if active is None else None)
        if not stop.stopped:
            return _ended(layout, ActOutcome.FAILED_RETURNED, target, _STOP_WITHHELD.format(detail=stop.reason))
    before = update_record(lambda record: record.installing_toward(target), layout)
    migration = ports.migrate(baseline, target)
    if not migration.succeeded:
        return _failed_after_window(
            layout,
            target,
            active,
            _MIGRATION_FAILED.format(detail=migration.reason),
            ports,
            request.checkout,
            migration.unaccounted,
        )
    ports.switch(target)
    update_record(lambda record: record.activated(target), layout)
    verdict = ports.start_and_verify(target, None)
    if verdict.succeeded:
        if active is None:
            ports.publish_cli()
        return _completed(layout, target, ports)
    reason = _START_UNVERIFIED.format(revision=target, detail=verdict.reason)
    return _failed_after_switch(layout, target, before, reason, ports, request.checkout)


def _failed_after_window(
    layout: InstallationLayout,
    target: str,
    active: str | None,
    reason: str,
    ports: InstallPorts,
    checkout: Path | None,
    unaccounted: bool,
) -> InstallResult:
    """A failure inside the stopped window: recovery follows what the owners signalled.

    A migration step that could not be accounted for — a start the entrypoint could not record, or an
    entrypoint that ended without a clean answer — counts as a started migration whatever the record holds.
    """
    reached = read_record(layout).window_migrated(target)
    if unaccounted:
        reached = reached.with_unknown()
        _persist_unaccounted(layout, target)
    if reached.started:
        return _left_stopped(layout, target, reached, reason)
    return _returned(layout, target, active, reason, ports, checkout)


def _persist_unaccounted(layout: InstallationLayout, target: str) -> None:
    """Keep the uncertainty durable where the storage allows; the decision to stay stopped never depends on it."""
    try:
        update_record(lambda record: record.migration_unaccounted(install_target=target), layout)
    except (OSError, ValidationError):
        logger.error(_UNACCOUNTED_NOT_PERSISTED_EVENT, revision=target, exc_info=True)
        with suppress(OSError):
            leave_unrecorded_start(layout, target)


def _failed_after_switch(
    layout: InstallationLayout,
    target: str,
    before: InstallRecord,
    reason: str,
    ports: InstallPorts,
    checkout: Path | None,
) -> InstallResult:
    """A start that did not verify: it returns to the release it left only when no migration started.

    Nothing advances until the attempted release is recorded stopped, and the decision reads the record
    after that, so a migration started while the stop settled is counted.
    """
    unsettled = _settle(layout, target, reason, ports, InstallAct.INSTALL)
    if unsettled is not None:
        return unsettled
    record = read_record(layout)
    if record.migrated.started:
        return _left_stopped(layout, target, record.migrated, reason)
    ports.switch(before.active)
    update_record(lambda current: current.restored_from(before), layout)
    return _returned(layout, target, before.active, reason, ports, checkout)


def _returned(
    layout: InstallationLayout,
    target: str,
    active: str | None,
    reason: str,
    ports: InstallPorts,
    checkout: Path | None,
) -> InstallResult:
    """Return the previously active release, or the checkout's platform, to service and record the failure."""
    update_record(lambda record: record.returned_to_previous(), layout)
    if active is not None or checkout is not None:
        restored = ports.start_and_verify(active, checkout if active is None else None)
        if not restored.succeeded:
            reason += _RESTORE_UNVERIFIED.format(detail=restored.reason)
    return _ended(layout, ActOutcome.FAILED_RETURNED, target, reason)


def _settle(
    layout: InstallationLayout, revision: str, reason: str, ports: InstallPorts, act: InstallAct
) -> InstallResult | None:
    """Stop the release that was attempted; ``None`` once the lifecycle recorded it stopped.

    A stop is withheld while the attempted daemon cannot yet prepare, which is the ordinary state of a
    daemon still starting and not listening on its API. While nothing listens, the lifecycle is asked
    again until the bound expires. The clock is read after each pause, immediately before the next
    attempt, so none starts after the bound; an attempt that is running when it expires still ends by
    its own waits. A stop that is withheld while the daemon answers, or that has not succeeded when the
    bound expires, is an unresolved recovery condition: nothing is switched back and nothing is started
    over a daemon that may still be running.
    """
    deadline = time.monotonic() + ADMISSION_WAIT_BOUND_SECONDS
    stop = ports.ensure_stopped()
    while not stop.stopped:
        if ports.daemon_serving():
            break
        time.sleep(_SETTLE_POLL_SECONDS)
        if time.monotonic() >= deadline:
            reason += _SETTLE_BOUND_EXPIRED.format(seconds=ADMISSION_WAIT_BOUND_SECONDS)
            break
        stop = ports.ensure_stopped()
    else:
        return None
    return _ended(layout, ActOutcome.FAILED_UNSETTLED, revision, reason + _NOT_SETTLED.format(detail=stop.reason), act)


def _left_stopped(
    layout: InstallationLayout,
    target: str,
    reached: MigratedState,
    reason: str,
    act: InstallAct = InstallAct.INSTALL,
) -> InstallResult:
    """A failure after a migration started: the daemon stays stopped and the record names what was reached."""
    try:
        update_record(lambda record: record.with_last_act(act, ActOutcome.FAILED_STOPPED, target, reason), layout)
    except (OSError, ValidationError):
        logger.error(_UNACCOUNTED_NOT_PERSISTED_EVENT, revision=target, exc_info=True)
    stores = reached.stores or (_UNKNOWN_STORES,)
    logger.error(_DECISION_EVENT, decision=InstallStatus.FAILED, revision=target, stores=stores, reason=reason)
    return InstallResult(
        status=InstallStatus.FAILED, revision=target, reason=reason, reached_stores=stores, left_stopped=True
    )


def _completed(layout: InstallationLayout, target: str, ports: InstallPorts) -> InstallResult:
    """Record the completed act, move running terminal interfaces onto it, prune, and publish and converge the installed release.

    Every running terminal interface is signalled to reload onto the new active release, and the prune keeps
    the active and previous releases plus every release a running terminal interface's record still names.
    Publication and fleet plumbing convergence follow the completed install and never change which release is
    active: a failure of either is recorded as owed and replayed by the next install of the active revision.
    """
    record = update_record(
        lambda current: current.with_last_act(InstallAct.INSTALL, ActOutcome.COMPLETED, target, None).publication_owed(
            target
        ),
        layout,
    )
    held = _after_reload_held_revisions(ports)
    if held is not None:
        ports.prune(frozenset(revision for revision in (record.active, record.previous, *held) if revision is not None))
    logger.info(_DECISION_EVENT, decision=InstallStatus.COMPLETED, revision=target)
    return InstallResult(
        status=InstallStatus.COMPLETED, revision=target, publication_failure=_publish(target, ports, layout)
    )


def _after_reload_held_revisions(ports: InstallPorts) -> frozenset[str] | None:
    """Reload running terminal interfaces, then name the releases they still hold; ``None`` when a hold is unknown.

    A failed reload never changes the act's outcome. A registry that cannot be read, or a record that names no
    revision, leaves a running terminal interface's dependency unknown, so the act prunes nothing: a later
    install prunes, and a retained release costs only disk.
    """
    try:
        ports.reload_tuis()
    except OSError as error:
        logger.error(_TUI_RELOAD_FAILED_EVENT, error=str(error))
    try:
        held = ports.held_tui_revisions()
    except OSError as error:
        logger.error(_TUI_REGISTRY_UNREADABLE_EVENT, error=str(error))
        return None
    if None in held:
        logger.warning(_TUI_HOLD_UNKNOWN_EVENT)
        return None
    return frozenset(revision for revision in held if revision is not None)


def _publish(revision: str, ports: InstallPorts, layout: InstallationLayout) -> str | None:
    """Publish and converge ``revision`` and record what is still owed; the failure detail, or ``None`` when both finished."""
    failure = ports.publish(revision)
    update_record(
        lambda record: record.published() if failure is None else record.publication_owed(revision, failure), layout
    )
    if failure is not None:
        logger.error(_PUBLICATION_EVENT, revision=revision, failure=failure)
    return failure


def _replay_publication(revision: str, ports: InstallPorts, layout: InstallationLayout) -> str | None:
    """Replay the publication and convergence the active release still owes, when it owes them."""
    owed = read_record(layout).publication
    if owed is None or owed.revision != revision:
        return None
    return _publish(revision, ports, layout)


def _ended(
    layout: InstallationLayout, outcome: ActOutcome, revision: str, reason: str, act: InstallAct = InstallAct.INSTALL
) -> InstallResult:
    """Record an act that ended without changing which release is active."""
    update_record(lambda record: record.with_last_act(act, outcome, revision, reason), layout)
    status = InstallStatus.REFUSED if outcome is ActOutcome.REFUSED else InstallStatus.FAILED
    log = logger.info if status is InstallStatus.REFUSED else logger.error
    log(_DECISION_EVENT, decision=status, revision=revision, reason=reason)
    return InstallResult(status=status, revision=revision, reason=reason)


def _preparation_reason(error: ReleasePreparationError) -> str:
    return _PREPARATION_FAILED.format(step=error.step.value, detail=error.detail)


def rollback_refusal(record: InstallRecord) -> str | None:
    """The sentence naming why the record offers no rollback, or ``None`` when it offers one."""
    refusal = record.rollback_refusal()
    if refusal is RollbackRefusal.MIGRATION_STARTED:
        window_stores = record.installing.migrated.stores if record.installing is not None else ()
        stores = tuple(sorted({*record.migrated.stores, *window_stores})) or (_UNKNOWN_STORES,)
        return _MIGRATIONS_STARTED.format(stores=_STORE_SEPARATOR.join(stores))
    if refusal is RollbackRefusal.INSTALL_UNSETTLED and record.installing is not None:
        return _INSTALL_UNSETTLED.format(target=record.installing.target)
    if refusal is RollbackRefusal.NO_PREVIOUS_RELEASE:
        return _NO_PREVIOUS
    return None


def rollback(ports: InstallPorts, layout: InstallationLayout | None = None) -> InstallResult:
    """Return the platform to the previous release, only while no migration has started since activation."""
    resolved = layout or InstallationLayout()
    try:
        with ports.exclusive():
            return _rollback(ports, resolved)
    except InstallInProgress:
        return InstallResult(status=InstallStatus.REFUSED, revision=None, reason=_IN_PROGRESS)


def _rollback(ports: InstallPorts, layout: InstallationLayout) -> InstallResult:
    before = read_record(layout)
    previous = before.previous
    refusal = rollback_refusal(before)
    if refusal is None and previous is not None and not layout.release_path(previous).is_dir():
        refusal = _PREVIOUS_GONE.format(revision=previous)
    if refusal is not None:
        logger.info(_DECISION_EVENT, decision=InstallStatus.REFUSED, act=InstallAct.ROLLBACK, reason=refusal)
        return _ended(layout, ActOutcome.REFUSED, previous or _NO_REVISION, refusal, InstallAct.ROLLBACK)
    assert previous is not None
    if ports.daemon_serving():
        stop = ports.stop(None)
        if not stop.stopped:
            reason = _STOP_WITHHELD.format(detail=stop.reason)
            return _ended(layout, ActOutcome.FAILED_RETURNED, previous, reason, InstallAct.ROLLBACK)
    # Owners may have signalled while the stop settled accepted work: judge again from the settled record.
    settled = rollback_refusal(read_record(layout))
    if settled is not None:
        restored = ports.start_and_verify(before.active, None)
        if not restored.succeeded:
            settled += _RESTORE_UNVERIFIED.format(detail=restored.reason)
        logger.info(_DECISION_EVENT, decision=InstallStatus.REFUSED, act=InstallAct.ROLLBACK, reason=settled)
        return _ended(layout, ActOutcome.REFUSED, previous, settled, InstallAct.ROLLBACK)
    ports.switch(previous)
    update_record(lambda record: record.rolled_back(), layout)
    verdict = ports.start_and_verify(previous, None)
    if verdict.succeeded:
        update_record(
            lambda record: record.with_last_act(InstallAct.ROLLBACK, ActOutcome.COMPLETED, previous, None), layout
        )
        logger.info(_DECISION_EVENT, decision=InstallStatus.COMPLETED, act=InstallAct.ROLLBACK, revision=previous)
        return InstallResult(status=InstallStatus.COMPLETED, revision=previous)
    return _rollback_unverified(before, previous, verdict, ports, layout)


def _rollback_unverified(
    before: InstallRecord, previous: str, verdict: StepVerdict, ports: InstallPorts, layout: InstallationLayout
) -> InstallResult:
    """The previous release did not verify: the release rolled back from is known to serve this state, so it returns."""
    reason = _START_UNVERIFIED.format(revision=previous, detail=verdict.reason)
    unsettled = _settle(layout, previous, reason, ports, InstallAct.ROLLBACK)
    if unsettled is not None:
        return unsettled
    reached = read_record(layout).migrated
    if reached.started:
        return _left_stopped(layout, previous, reached, reason, InstallAct.ROLLBACK)
    ports.switch(before.active)
    update_record(lambda record: record.restored_from(before), layout)
    restored = ports.start_and_verify(before.active, None)
    if not restored.succeeded:
        reason += _RESTORE_UNVERIFIED.format(detail=restored.reason)
    return _ended(layout, ActOutcome.FAILED_RETURNED, previous, reason, InstallAct.ROLLBACK)
