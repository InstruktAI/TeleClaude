"""Migration start signals: each store's owner reports, before it changes anything, that it is starting one.

A migration is an owner's own forward step over data or schema that already exists — a ledger entry
about to be applied, a stored revision behind the code's, a retired shape about to be rewritten.
Creating a store or table that did not exist is not one. Whether a migration runs from a ledger or
when its store is opened, the owner calls ``signal_migration_started`` at the point where it knows a
step will change something, and never classifies what the step did: a started migration counts as a
change (``local/projects/teleclaude/spec/feature/reconciliation/installed-releases``).

The sink is bound to the installation whose state is migrating. A signal is written to the install
record only when the signalling process runs the installation's active release, or is the install
act's migration entrypoint for the release being installed, which names its target release through
``bind_install_target``. Code loaded from any other checkout — a slug worktree migrating its isolated
home's stores, a development checkout — signals to nothing. A signal the record cannot take raises:
the owner has not changed anything yet, so the migration does not start; evidence of the uncertainty is left
beside the record, where it counts as a started migration.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from enum import IntEnum, StrEnum

from pydantic import ValidationError

from teleclaude.core.reconciliation.installation import (
    InstallationLayout,
    leave_unrecorded_start,
    runs_active_release,
    update_record,
)

_SIGNAL_NOT_RECORDED = "migration start in {store} could not be recorded: {error}"


class MigrationStore(StrEnum):
    """The stores whose owners signal started migrations."""

    INSTALLATION = "installation"
    CONFIGURATION = "configuration"
    CORE_DATABASE = "core_database"
    EVENTS = "events"
    MIRRORS = "mirrors"
    TODOS = "todos"
    HOOK_OUTBOX = "hook_outbox"


class MigrationExitCode(IntEnum):
    """Exit statuses the entrypoint publishes; argparse owns the usage-error status.

    ``FAILED`` answers that nothing started a migration the record does not hold; ``UNACCOUNTED`` that a
    start could not be recorded, which counts as a started migration. Any other status, or none, is
    uncertain too, and the install act treats it as such.
    """

    SUCCEEDED = 0
    FAILED = 1
    UNACCOUNTED = 3


class MigrationSignalError(RuntimeError):
    """A migration start could not be recorded, so the migration must not start."""


_install_target: str | None = None
_signalled: set[tuple[MigrationStore, str | None]] = set()
_unrecorded = False


def unrecorded_signal_seen() -> bool:
    """Whether this process met a migration start it could not record.

    This is evidence held in the process itself, independent of any write: an entrypoint reports it by
    its exit status, so the uncertainty reaches the install act even when the storage that failed to take
    the signal also fails to take a marker.
    """
    return _unrecorded


@contextmanager
def bind_install_target(revision: str) -> Iterator[None]:
    """Count this process's signals against the release being installed, which is not active yet."""
    global _install_target
    previous = _install_target
    _install_target = revision
    try:
        yield
    finally:
        _install_target = previous


def signal_migration_started(store: MigrationStore, layout: InstallationLayout | None = None) -> None:
    """Report that ``store``'s owner is about to run a migration step that changes something."""
    target = _install_target
    resolved = layout or InstallationLayout()
    if target is None and not runs_active_release(resolved):
        return
    key = (store, target)
    if key in _signalled:
        return
    try:
        update_record(lambda record: record.migration_started(store.value, install_target=target), resolved)
    except (OSError, ValidationError) as error:
        global _unrecorded
        _unrecorded = True
        # The migration stops before it changes anything, but the uncertainty stays observable: a marker
        # beside the record counts as a started migration for recovery and for rollback.
        with suppress(OSError):
            leave_unrecorded_start(resolved, target)
        raise MigrationSignalError(_SIGNAL_NOT_RECORDED.format(store=store.value, error=error)) from error
    _signalled.add(key)
