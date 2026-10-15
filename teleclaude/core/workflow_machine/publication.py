"""The workflow publication: the driver and child declarations the machine routes by.

The machine takes its steps from the ``workflow`` headers of the published procedures
(``local/projects/teleclaude/spec/feature/workflow/item-lifecycle``). A publication is the set of
driver procedures and their children read once from the deployed merged index, with the digest of
the declarations it holds. A driver is initialized under one publication and keeps it: the snapshot
travels with the session's invocation, and the child is launched from it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import yaml

from teleclaude.core.models import JsonDict
from teleclaude.core.models._session import NO_WORKFLOW_PUBLICATION
from teleclaude.docs_subscriptions import IndexKey
from teleclaude.entry_declarations import (
    EntryDeclarations,
    EntryKey,
    WorkflowDeclaration,
    WorkflowKey,
    parse_entry_declarations,
)
from teleclaude.paths import GLOBAL_DOCS_DIR
from teleclaude.types.workflow_record import DrivenPhase

INDEX_FILE_NAME: Final = "index.yaml"
PROCEDURE_TYPE: Final = "procedure"
UTF8: Final = "utf-8"
JSON_SEPARATORS: Final = (",", ":")
NO_DRIVER_TEMPLATE: Final = "no published procedure drives {phase}"
UNREADABLE_TEMPLATE: Final = "the published declarations of {procedure} cannot be read"


class SnapshotKey(StrEnum):
    """The keys of a serialized publication snapshot."""

    DIGEST = "digest"
    PROCEDURES = "procedures"


class PublicationError(ValueError):
    """The published declarations do not describe a usable driver for a phase."""


@dataclass(frozen=True)
class DeclaredProcedure:
    """A procedure of the publication: its identity and its entry declarations."""

    procedure_id: str
    declarations: EntryDeclarations


@dataclass(frozen=True)
class WorkflowPublication:
    """The drivers and children of one publication, with the digest of the declarations they came from."""

    procedures: tuple[tuple[str, JsonDict], ...]
    digest: str

    def declared(self, procedure_id: str) -> DeclaredProcedure:
        """The entry declarations the publication holds for a procedure."""
        for held_id, payload in self.procedures:
            if held_id == procedure_id:
                declarations = parse_entry_declarations(payload).declarations
                if declarations is None:
                    raise PublicationError(UNREADABLE_TEMPLATE.format(procedure=procedure_id))
                return DeclaredProcedure(procedure_id, declarations)
        raise PublicationError(UNREADABLE_TEMPLATE.format(procedure=procedure_id))

    def driver_for(self, phase: DrivenPhase) -> tuple[DeclaredProcedure, WorkflowDeclaration]:
        """The procedure that drives the phase, with its workflow declaration."""
        for procedure_id, _ in self.procedures:
            declared = self.declared(procedure_id)
            workflow = declared.declarations.workflow
            if workflow is not None and phase in workflow.drives:
                return declared, workflow
        raise PublicationError(NO_DRIVER_TEMPLATE.format(phase=phase.value))

    def child_of(self, workflow: WorkflowDeclaration) -> DeclaredProcedure:
        """The child procedure a driver's declaration names."""
        return self.declared(workflow.child)

    def to_json(self) -> str:
        """The serialized snapshot a session's invocation carries."""
        return json.dumps(
            {
                SnapshotKey.DIGEST: self.digest,
                SnapshotKey.PROCEDURES: [[procedure_id, payload] for procedure_id, payload in self.procedures],
            },
            separators=JSON_SEPARATORS,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: str) -> WorkflowPublication:
        """Restore a snapshot a session's invocation carried."""
        data = json.loads(raw)
        return cls(
            procedures=tuple((str(item[0]), dict(item[1])) for item in data[SnapshotKey.PROCEDURES]),
            digest=str(data[SnapshotKey.DIGEST]),
        )


def _digest_of(procedures: list[tuple[str, JsonDict]]) -> str:
    canonical = json.dumps(procedures, separators=JSON_SEPARATORS, sort_keys=True)
    return hashlib.sha256(canonical.encode(UTF8)).hexdigest()


def published_workflow_publication() -> WorkflowPublication:
    """Read the driver procedures and their children from the deployed merged index, live entries only."""
    raw = (GLOBAL_DOCS_DIR / INDEX_FILE_NAME).read_bytes()
    payload = yaml.safe_load(raw.decode(UTF8)) or {}
    snippets = payload.get(IndexKey.SNIPPETS, []) if isinstance(payload, dict) else []
    live = {
        str(entry[IndexKey.ID]): entry
        for entry in snippets
        if isinstance(entry, dict)
        and entry.get(IndexKey.TYPE) == PROCEDURE_TYPE
        and not entry.get(IndexKey.DELIVERED_BY)
        and isinstance(entry.get(IndexKey.ID), str)
    }
    held: dict[str, JsonDict] = {}
    for procedure_id, entry in live.items():
        if EntryKey.WORKFLOW.value not in entry:
            continue
        held[procedure_id] = dict(entry)
        declaration = entry[EntryKey.WORKFLOW.value]
        child = declaration.get(WorkflowKey.CHILD.value) if isinstance(declaration, dict) else None
        if isinstance(child, str) and child in live:
            held[child] = dict(live[child])
    procedures = sorted(held.items())
    return WorkflowPublication(procedures=tuple(procedures), digest=_digest_of(procedures))


@dataclass(frozen=True)
class DriverInitialization:
    """What a lifecycle driver is initialized under: its snapshot and the declarations read from that same snapshot."""

    snapshot: str
    declarations: EntryDeclarations | None


def driver_initialization(procedure_id: str) -> DriverInitialization:
    """Read the publication once and derive both the snapshot and the driver's declarations from it.

    A procedure that is not a lifecycle driver has neither.
    """
    publication = published_workflow_publication()
    try:
        declared = publication.declared(procedure_id)
    except PublicationError:
        return DriverInitialization(NO_WORKFLOW_PUBLICATION, None)
    if declared.declarations.workflow is None:
        return DriverInitialization(NO_WORKFLOW_PUBLICATION, None)
    return DriverInitialization(publication.to_json(), declared.declarations)


def pinned_declarations(snapshot: str, procedure_id: str) -> EntryDeclarations | None:
    """The declarations a driver's snapshot holds for a procedure; None when there is no snapshot."""
    if not snapshot:
        return None
    return WorkflowPublication.from_json(snapshot).declared(procedure_id).declarations
