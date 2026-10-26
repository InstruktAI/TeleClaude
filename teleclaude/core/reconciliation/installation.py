"""The installation: where releases live, which one is active, and what the install record says happened.

One installation per machine lives under the XDG data directory in the platform's own folder: a kept
repository, one release per installed revision as a worktree of it, the ``current`` pointer to the
active release, and the install record. The installation is identified by that location and by the
pointer alone; a caller's directory, an imported module's location, the release channel or the target
of the published ``telec`` identify nothing
(``local/projects/teleclaude/spec/feature/reconciliation/release-checkout``).

The record is the state rollback, status and failure handling read. Writers go through
``update_record`` so concurrent signalers and the install act serialize on one lock.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from teleclaude.file_transaction import file_transaction
from teleclaude.paths import INSTALLATION_ROOT, REPO_ROOT

_REPOSITORY_DIRECTORY = "repository"
_RELEASES_DIRECTORY = "releases"
_CURRENT_POINTER = "current"
_RECORD_FILENAME = "install-record.json"
_ASSESSMENT_RECORD_FILENAME = "assessment-record.json"
_UNRECORDED_START_FILENAME = "unrecorded-migration-start"
# The marker content that names the active release rather than an install target.
_MARKER_ACTIVE_RELEASE = ""
_OUTER_MARKER_FILENAME = "{root}.unrecorded-migration-start"
_TEXT_ENCODING = "utf-8"
_RECORD_SCHEMA_VERSION: Literal[1] = 1
_STAGED_POINTER_PREFIX = ".current."


class InstallAct(StrEnum):
    """The acts that change which release is active."""

    INSTALL = "install"
    ROLLBACK = "rollback"


class ActOutcome(StrEnum):
    """How the most recent act ended.

    ``FAILED_RETURNED`` left the previously active release active and serving; ``FAILED_STOPPED``
    left the daemon stopped after a migration started, to be repaired forward; ``FAILED_UNSETTLED``
    could not stop the attempted daemon through its lifecycle, because the stop was withheld while it
    answered or it was still not stoppable when the settlement bound expired, so nothing was switched back.
    """

    COMPLETED = "completed"
    REFUSED = "refused"
    FAILED_RETURNED = "failed_returned"
    FAILED_STOPPED = "failed_stopped"
    FAILED_UNSETTLED = "failed_unsettled"


class RollbackRefusal(StrEnum):
    """Why the record does not offer a rollback."""

    NO_PREVIOUS_RELEASE = "no_previous_release"
    MIGRATION_STARTED = "migration_started"
    INSTALL_UNSETTLED = "install_unsettled"


class MigratedState(BaseModel):
    """The stores whose owners signalled a started migration, and whether a start could not be accounted for.

    A started migration counts as a change whatever it did. ``unknown`` records a start the record could
    not take: the migration was stopped before it changed anything, but the uncertainty stays observable and
    counts as a started migration for recovery and rollback.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    stores: tuple[str, ...] = ()
    unknown: bool = False

    @property
    def started(self) -> bool:
        """Whether any migration is known or presumed to have started."""
        return bool(self.stores) or self.unknown

    def with_store(self, store: str) -> MigratedState:
        """This state after ``store``'s owner signalled a started migration."""
        return MigratedState(stores=tuple(sorted({*self.stores, store})), unknown=self.unknown)

    def with_unknown(self) -> MigratedState:
        """This state after a start that could not be recorded."""
        return MigratedState(stores=self.stores, unknown=True)


class InstallingWindow(BaseModel):
    """An install in progress: its target and the migrations its stopped window has started so far."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: str
    migrated: MigratedState = MigratedState()

    def left_open(self) -> MigratedState:
        """What this window leaves behind when a later attempt takes its place or it is activated for another target.

        A window found open was never closed as proven migration-free — a settled install closes it — so
        what it changed cannot be ruled out: the migrations it holds, or an unattributed start when it
        holds none. Every transition that moves past an open window carries this, never an empty state.
        """
        return self.migrated if self.migrated.started else self.migrated.with_unknown()


class PublicationState(BaseModel):
    """Publication an installed release still owes: its revision and why the last attempt did not complete."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: str
    failure: str | None = None


class LastAct(BaseModel):
    """The most recent install or rollback, its outcome and the reason it ended that way."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    act: InstallAct
    outcome: ActOutcome
    revision: str
    reason: str | None = None
    at: datetime


class InstallRecord(BaseModel):
    """What the installation knows about its own releases and the effects of the active one."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = _RECORD_SCHEMA_VERSION
    active: str | None = None
    previous: str | None = None
    migrated: MigratedState = MigratedState()
    installing: InstallingWindow | None = None
    publication: PublicationState | None = None
    last_act: LastAct | None = Field(default=None)

    def _with(self, **changes: object) -> InstallRecord:
        """This record with the named fields replaced."""
        return self.model_copy(update=changes)

    def installing_toward(self, target: str) -> InstallRecord:
        """This record once an install of ``target`` has opened its stopped window.

        Migrations a failed earlier install left standing in its window are still applied to the stores, so
        the new window carries them: the repair install judges recovery and rollback with them counted.
        A window found open was never closed as proven migration-free — an install that did settle closed
        it — so what it changed cannot be ruled out, and the new window carries that uncertainty too: only
        a completed forward repair, never the replacement of the window or a repair's own failure before
        it migrates, turns it into something the record can account for.
        """
        carried = self.installing.left_open() if self.installing is not None else MigratedState()
        return self._with(installing=InstallingWindow(target=target, migrated=carried))

    def migration_started(self, store: str, *, install_target: str | None) -> InstallRecord:
        """This record once ``store``'s owner signalled a started migration.

        Migrations of the active release count against it; migrations of the install window count
        against the release being installed, which becomes the active release only when it is switched.
        """
        if install_target is not None:
            window = self._window_for(install_target)
            return self._with(
                installing=InstallingWindow(target=install_target, migrated=window.migrated.with_store(store))
            )
        return self._with(migrated=self.migrated.with_store(store))

    def migration_unaccounted(self, *, install_target: str | None) -> InstallRecord:
        """This record once a migration start could not be recorded: counted as started, store unknown."""
        if install_target is not None:
            window = self._window_for(install_target)
            return self._with(
                installing=InstallingWindow(target=install_target, migrated=window.migrated.with_unknown())
            )
        return self._with(migrated=self.migrated.with_unknown())

    def _window_for(self, target: str) -> InstallingWindow:
        """The window of ``target``; a window open for another target is replaced by one that carries what it left."""
        window = self.installing
        if window is None:
            return InstallingWindow(target=target)
        if window.target == target:
            return window
        return InstallingWindow(target=target, migrated=window.left_open())

    def window_migrated(self, target: str) -> MigratedState:
        """The migrations counted against an install of ``target``: its window's, or what another open window left."""
        if self.installing is None:
            return MigratedState()
        if self.installing.target == target:
            return self.installing.migrated
        return self.installing.left_open()

    def activated(self, revision: str) -> InstallRecord:
        """This record once ``revision`` became the active release.

        The previous release is the one active before; the migrations the install window started are
        the active release's, so a rollback offered later accounts for them.
        """
        return self._with(
            active=revision,
            previous=self.active,
            migrated=self.window_migrated(revision),
            installing=None,
        )

    def returned_to_previous(self) -> InstallRecord:
        """This record once a failed install returned to the release that was active; its window is closed.

        A window that holds a started migration is never closed by a return: the record keeps it, because a
        return is only ever valid over a window the record can show to be migration-free.
        """
        if self.installing is not None and self.installing.migrated.started:
            return self
        return self._with(installing=None)

    def restored_from(self, before: InstallRecord) -> InstallRecord:
        """This record once a failed install returned the pointer to the release it left: its releases and migrations.

        Like a return, it never discards a started migration: over one the record is kept as it is.
        """
        if self.migrated.started or (self.installing is not None and self.installing.migrated.started):
            return self
        return self._with(active=before.active, previous=before.previous, migrated=before.migrated, installing=None)

    def rolled_back(self) -> InstallRecord:
        """This record once the previous release became active again; no further rollback is offered."""
        return self._with(active=self.previous, previous=None, migrated=MigratedState(), installing=None)

    def rollback_refusal(self) -> RollbackRefusal | None:
        """Why this record offers no rollback, or ``None`` when it offers one.

        A failed install's window still holds the migrations it started, so it counts as much as the
        active release's own. A window that is still open was never closed as proven migration-free — an
        install that ended without recording its outcome leaves it so — and what it changed cannot be ruled
        out, whatever the record can or cannot show of it; only an install that settles it reopens rollback.
        """
        window_started = self.installing is not None and self.installing.migrated.started
        if self.migrated.started or window_started:
            return RollbackRefusal.MIGRATION_STARTED
        if self.installing is not None:
            return RollbackRefusal.INSTALL_UNSETTLED
        if self.previous is None:
            return RollbackRefusal.NO_PREVIOUS_RELEASE
        return None

    def publication_owed(self, revision: str, failure: str | None = None) -> InstallRecord:
        """This record once the publication of ``revision`` is owed, with why the last attempt failed."""
        return self._with(publication=PublicationState(revision=revision, failure=failure))

    def published(self) -> InstallRecord:
        """This record once nothing is owed."""
        return self._with(publication=None)

    def with_last_act(self, act: InstallAct, outcome: ActOutcome, revision: str, reason: str | None) -> InstallRecord:
        """This record with the act that just ended."""
        return self._with(
            last_act=LastAct(act=act, outcome=outcome, revision=revision, reason=reason, at=datetime.now(UTC))
        )


@dataclass(frozen=True)
class InstallationLayout:
    """Where one installation keeps its parts. Nothing here lives inside a release or the platform home."""

    root: Path = INSTALLATION_ROOT

    @property
    def repository(self) -> Path:
        """The kept repository whose remote is the source the installation follows."""
        return self.root / _REPOSITORY_DIRECTORY

    @property
    def releases(self) -> Path:
        """The folder holding one worktree per installed revision."""
        return self.root / _RELEASES_DIRECTORY

    @property
    def current(self) -> Path:
        """The active-release pointer every live surface addresses."""
        return self.root / _CURRENT_POINTER

    @property
    def record_path(self) -> Path:
        """The install record."""
        return self.root / _RECORD_FILENAME

    @property
    def assessment_record_path(self) -> Path:
        """The assessment record: a sibling file, so a release that predates it never reads a record carrying it."""
        return self.root / _ASSESSMENT_RECORD_FILENAME

    @property
    def unrecorded_start_paths(self) -> tuple[Path, ...]:
        """The markers left when a migration start could not be recorded; content names the install target, if any.

        One lies beside the record and one beside the installation root, so storage that refuses the record
        directory does not also take every trace of the uncertainty.
        """
        return (
            self.root / _UNRECORDED_START_FILENAME,
            self.root.parent / _OUTER_MARKER_FILENAME.format(root=self.root.name),
        )

    def release_path(self, revision: str) -> Path:
        """The folder of the release at ``revision``."""
        return self.releases / revision

    def active_release(self) -> Path | None:
        """The release folder the pointer names, or ``None`` when nothing is active."""
        pointer = self.current
        if not pointer.is_symlink():
            return None
        target = pointer.resolve()
        return target if target.is_dir() else None

    def active_revision(self) -> str | None:
        """The revision of the active release, or ``None`` when nothing is active."""
        release = self.active_release()
        return self.release_revision(release) if release is not None else None

    def release_revision(self, path: Path) -> str | None:
        """The revision a release folder holds, or ``None`` when ``path`` is not a release of this installation."""
        resolved = path.resolve()
        if resolved.parent != self.releases.resolve() or not resolved.is_dir():
            return None
        return resolved.name

    def installed_revisions(self) -> tuple[str, ...]:
        """The revisions that have a release folder."""
        if not self.releases.is_dir():
            return ()
        return tuple(sorted(entry.name for entry in self.releases.iterdir() if entry.is_dir()))


def is_installed_release(root: Path, layout: InstallationLayout | None = None) -> bool:
    """Whether ``root`` is a release of the installation, active or not."""
    return (layout or InstallationLayout()).release_revision(root) is not None


def loaded_release_revision(layout: InstallationLayout | None = None) -> str | None:
    """The revision of the release this process's code was loaded from, or ``None`` for any other checkout."""
    return (layout or InstallationLayout()).release_revision(REPO_ROOT)


def runs_active_release(layout: InstallationLayout | None = None) -> bool:
    """Whether this process's code was loaded from the installation's active release."""
    resolved = layout or InstallationLayout()
    loaded = resolved.release_revision(REPO_ROOT)
    return loaded is not None and loaded == resolved.active_revision()


def _marker_target(layout: InstallationLayout) -> tuple[bool, str | None]:
    """Whether a migration start could not be recorded, and against which install target (``None``: the active release)."""
    for marker in layout.unrecorded_start_paths:
        if marker.is_file():
            target = marker.read_text(encoding=_TEXT_ENCODING).strip()
            return True, None if target == _MARKER_ACTIVE_RELEASE else target
    return False, None


def _with_unrecorded_start(record: InstallRecord, layout: InstallationLayout) -> InstallRecord:
    """The record with a start that could not be recorded folded in as a started migration."""
    present, target = _marker_target(layout)
    return record.migration_unaccounted(install_target=target) if present else record


def read_record(layout: InstallationLayout | None = None) -> InstallRecord:
    """The install record, or an empty one when the installation has none yet; unrecorded starts count as started."""
    resolved = layout or InstallationLayout()
    path = resolved.record_path
    record = (
        InstallRecord.model_validate_json(path.read_text(encoding=_TEXT_ENCODING))
        if path.is_file()
        else InstallRecord()
    )
    return _with_unrecorded_start(record, resolved)


def update_record(
    transform: Callable[[InstallRecord], InstallRecord], layout: InstallationLayout | None = None
) -> InstallRecord:
    """Replace the record with ``transform`` of its current value, atomically under one lock; return the result.

    A migration start an owner could not record was left beside the record; it is folded into the value
    ``transform`` sees and persisted with it, and the marker is withdrawn only once the record holds it.
    """
    resolved = layout or InstallationLayout()
    with file_transaction(resolved.record_path) as transaction:
        text = transaction.read_text(encoding=_TEXT_ENCODING)
        current = InstallRecord.model_validate_json(text) if text.strip() else InstallRecord()
        updated = transform(_with_unrecorded_start(current, resolved))
        transaction.replace_text(updated.model_dump_json(), encoding=_TEXT_ENCODING)
        for marker in resolved.unrecorded_start_paths:
            marker.unlink(missing_ok=True)
    return updated


def leave_unrecorded_start(layout: InstallationLayout, install_target: str | None) -> None:
    """Leave evidence, at every location the storage still takes, that a migration start could not be recorded.

    Raises ``OSError`` only when no location took it; the caller then holds the in-process evidence alone.
    """
    content = _MARKER_ACTIVE_RELEASE if install_target is None else install_target
    failure: OSError | None = None
    left = False
    for marker in layout.unrecorded_start_paths:
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(content, encoding=_TEXT_ENCODING)
            left = True
        except OSError as error:
            failure = error
    if not left and failure is not None:
        raise failure


def switch_current(layout: InstallationLayout, revision: str | None) -> None:
    """Point ``current`` at the release of ``revision`` in one atomic step; ``None`` withdraws the pointer.

    The pointer is relative to the installation root, so the installation can be moved as a whole.
    """
    if revision is None:
        layout.current.unlink(missing_ok=True)
        return
    layout.root.mkdir(parents=True, exist_ok=True)
    staged = layout.root / f"{_STAGED_POINTER_PREFIX}{uuid4().hex}"
    staged.symlink_to(Path(_RELEASES_DIRECTORY) / revision)
    try:
        os.replace(staged, layout.current)
    except OSError:
        staged.unlink(missing_ok=True)
        raise
