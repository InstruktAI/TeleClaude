"""Shared observation helpers of the item journeys R2, R3 and R5 (plan and task creation, hold and release, removal).

The journeys\' assertions are the independently reviewed ones recorded in the shared handoff workspace
(`journeys/r2-r3-r5-assertion-draft.md`, approved at exact SHA-256
8055cc9cf4741c32e655e52dea679087e7ded6fbe9c40f715debbf1c382c9ceb); they reuse the R1/R4 primitives (`workflow_creation`)
and add the operation, removed-list and removed-show reads, the allowed-difference rule for writing steps, and the
no-write check after a refusal. Every observation is a public CLI read through a fresh process on the owner terminal;
the controller imports no application module and creates no record, identity or authentication state.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Final

from tools.ci import workflow_creation as creation
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_publication as publication
from tools.ci.workflow_creation import Observer, SessionView

TELEC: Final = creation.TELEC
TODO: Final = creation.TODO
SHOW: Final = creation.SHOW
LIST: Final = creation.LIST
CREATE: Final = creation.CREATE
REMOVE: Final = "remove"
UPDATE: Final = "update"
REACTIVATE: Final = "reactivate"
REMOVED_ONLY_FLAG: Final = "--removed-only"
INCLUDE_REMOVED_FLAG: Final = creation.INCLUDE_REMOVED
INCLUDE_ARTIFACT_CONTENT: Final = creation.INCLUDE_ARTIFACT_CONTENT
JSON_FLAG: Final = creation.JSON_FLAG
APPROVED_FLAG: Final = creation.APPROVED_FLAG
KIND_OPTION: Final = creation.KIND_OPTION
PLAN_FLAG: Final = "--plan"
HOLD_FLAG: Final = "--hold"
RELEASE_FLAG: Final = "--release"
REASON_OPTION: Final = "--reason"

FIELD_OPERATION: Final = "operation_id"
FIELD_REMOVED: Final = "removed"
FIELD_REMOVED_AT: Final = "removed_at"
FIELD_STATUS: Final = "status"
FIELD_SLUG: Final = "slug"
OPERATION_SECONDS: Final = 60.0
SETTLE_SECONDS: Final = creation.SETTLE_SECONDS
ROADMAP_UPDATED_AT: Final = "roadmap.updated_at"
STATUS_REMOVED: Final = "removed"

DETAIL_RECEIPT: Final = "`{command}` printed no operation receipt: exit {status}, {output!r}"
DETAIL_OPERATION: Final = "operation {operation} ended {state!r} with {error!r}, not completed without an error"
DETAIL_REMOVED_READ: Final = "`todo list --removed-only --json` did not decode: exit {status}, {output!r}"
DETAIL_SHOW_REMOVED: Final = "`todo show {slug} --include-removed` failed: exit {status}, {output!r}"
DETAIL_DIFFERENCES: Final = "{what}: the item differs from before at paths outside the allowed set {allowed!r}: {paths}"
DETAIL_WRITE: Final = "{case}: the item read {when} differs from before; differing paths: {paths}"
DETAIL_ABSENT: Final = "{case}: the item is absent {when}"
DETAIL_SLUGS: Final = "{case}: the set of slugs changed from {before!r} to {after!r}"
DETAIL_ALLOWED_MISSING: Final = "{what}: the item is absent after the write"

type Json = Mapping[str, object]


def completed_operation(observer: Observer, command: str, output: str, status: int | None) -> Json:
    """A receipt-backed verb\'s operation read to its terminal state; anything but completed without error fails."""
    receipt = foundation.json_object(output)
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if status != 0 or not isinstance(operation, str) or not operation:
        raise creation.binding_failure(DETAIL_RECEIPT.format(command=command, status=status, output=output[-300:]))
    state = publication.await_terminal(observer, operation, OPERATION_SECONDS)
    error = state.get(publication.FIELD_ERROR)
    if state.get(publication.FIELD_STATE) != publication.STATE_COMPLETED or error not in (None, creation.EMPTY):
        raise creation.platform_failure(
            DETAIL_OPERATION.format(operation=operation, state=state.get(publication.FIELD_STATE), error=error)
        )
    return state


def removed_nodes(observer: Observer) -> list[Json]:
    """O5: the nodes of `todo list --removed-only --json`; an empty answer is no nodes."""
    outcome = observer.run((TELEC, TODO, LIST, REMOVED_ONLY_FLAG, JSON_FLAG))
    payload = creation.decode_object(outcome.output)
    if outcome.exit_status != 0 or payload is None:
        raise creation.binding_failure(
            DETAIL_REMOVED_READ.format(status=outcome.exit_status, output=outcome.output[-300:])
        )
    nodes = payload.get(FIELD_REMOVED, [])
    return [node for node in nodes if isinstance(node, Mapping)] if isinstance(nodes, list) else []


def show_removed(observer: Observer, slug: str) -> Json | None:
    """O6: the shown payload of a removed item, or None when the platform says there is no such slug."""
    outcome = observer.run((TELEC, TODO, SHOW, slug, INCLUDE_REMOVED_FLAG, INCLUDE_ARTIFACT_CONTENT))
    if outcome.exit_status == 0:
        payload = creation.decode_object(outcome.output)
        if payload is None:
            raise creation.binding_failure(
                creation.DETAIL_UNDECODABLE.format(
                    what=f"todo show {slug} --include-removed", output=outcome.output[-300:]
                )
            )
        return payload
    if creation.NOT_FOUND_PHRASE.format(slug=slug) in outcome.output:
        return None
    raise creation.binding_failure(
        DETAIL_SHOW_REMOVED.format(slug=slug, status=outcome.exit_status, output=outcome.output[-300:])
    )


def listing_slugs(observer: Observer) -> set[str]:
    """O7: the slugs of the default sections of `todo list --json`."""
    outcome = observer.run((TELEC, TODO, LIST, JSON_FLAG))
    payload = creation.decode_object(outcome.output)
    if outcome.exit_status != 0 or payload is None:
        raise creation.binding_failure(
            creation.DETAIL_UNDECODABLE.format(what="todo list", output=outcome.output[-300:])
        )
    return creation.collect_slugs(payload)


def require_only_changes(what: str, before: Json, after: Json, allowed: Sequence[str]) -> None:
    """Two reads of one item are deeply equal except at the allowed paths (and below them)."""
    outside = [
        path
        for path in creation.differences(before, after)
        if not any(
            path == prefix or path.startswith(f"{prefix}.") or path.startswith(f"{prefix}[") for prefix in allowed
        )
    ]
    if outside:
        raise creation.platform_failure(DETAIL_DIFFERENCES.format(what=what, allowed=list(allowed), paths=outside))


def quiescent(observer: Observer, slug: str, what: str) -> Json:
    """Two reads at least two seconds apart, deeply equal; otherwise something else is writing the item."""
    first = observer.show(slug)
    if first is None:
        raise creation.binding_failure(DETAIL_ABSENT.format(case=what, when="before the control"))
    time.sleep(creation.QUIESCENCE_GAP_SECONDS)
    second = observer.show(slug)
    if second is None or creation.differences(first, second):
        paths = creation.differences(first, second) if second is not None else ["absent"]
        raise creation.binding_failure(creation.DETAIL_NOT_QUIESCENT.format(paths=paths))
    return second


def require_nothing_written(
    observer: Observer, slug: str, case: str, before: Json, sessions: SessionView, slugs: set[str] | None = None
) -> None:
    """After a refusal: the item and the sessions are as before, now and five seconds later."""
    for when, pause in (("immediately", 0.0), ("five seconds later", SETTLE_SECONDS)):
        if pause:
            time.sleep(pause)
        after = observer.show(slug, retain=False)
        if after is None:
            raise creation.platform_failure(DETAIL_ABSENT.format(case=case, when=when))
        changed = creation.differences(before, after)
        if changed:
            raise creation.platform_failure(DETAIL_WRITE.format(case=case, when=when, paths=changed))
        creation.require_sessions_equal(sessions, observer.sessions(retain=False), when)
    if slugs is not None:
        now = observer.slugs(retain=False)
        if now != slugs:
            raise creation.platform_failure(DETAIL_SLUGS.format(case=case, before=sorted(slugs), after=sorted(now)))


def require_absent_everywhere(observer: Observer, slugs: Sequence[str], baseline: SessionView, what: str) -> None:
    """No slug of the list exists on any read path and no session appeared."""
    for slug in slugs:
        if observer.show(slug) is not None:
            raise creation.platform_failure(DETAIL_ABSENT.format(case=what, when=f"expected absent, {slug} is found"))
    found = observer.slugs()
    present = [slug for slug in slugs if slug in found]
    if present:
        raise creation.platform_failure(creation.DETAIL_SLUGS_CHANGED.format(case=what, before=[], after=present))
    creation.require_sessions_equal(baseline, observer.sessions(), what)
