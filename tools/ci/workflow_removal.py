"""Journey R5 of the workflow acceptance: soft removal and restoration of a plain preparation item.

The journey\'s assertions are the independently reviewed ones recorded in the shared handoff workspace
(`journeys/r2-r3-r5-assertion-draft.md`, section 4, approved at exact SHA-256
8055cc9cf4741c32e655e52dea679087e7ded6fbe9c40f715debbf1c382c9ceb; authority the pending
`local/projects/teleclaude/spec/feature/workflow/todo-management` soft removal and `.../item-lifecycle` restoration
classification). It proves that a removal is receipt-backed and leaves every default read path, that the retained
content stays readable and a removed item accepts no other change, that a restoration returns the same record in
`preparation` with no episode, and that a live twin blocks a restoration and is not disturbed. Only the simple restored
current-machine preparation record is covered: no legacy conversion, admission, held-ready recovery, forced removal
of a claimed item, purge or task dispatch.

Every observation is a public CLI command through a fresh process on the authenticated owner terminal; the controller
imports no application module and creates no record, identity or authentication state.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final

from tools.ci import acceptance_work as payload_work
from tools.ci import workflow_creation as creation
from tools.ci import workflow_items as items
from tools.ci.workflow_creation import Observer, SessionView
from tools.ci.workflow_foundation import FoundationHost

SLUG: Final = "ra-rm"
CONTENT: Final = "r5 removal content"
CONTENT_TWIN: Final = "r5 twin content"
KIND_FEATURE: Final = "feature"
PHASE_PREPARATION: Final = "preparation"
REASON_REFUSED: Final = "r5 refused"
ARTIFACTS: Final = "artifacts"
READ: Final = "read"
INPUT: Final = creation.INPUT_ARTIFACT
RESTORED_PHRASE: Final = "Restored todo: {slug}"
UPDATE_REFUSAL_PHRASES: Final = ("todo '{slug}' is removed and retained for", "telec todo reactivate --id <row-id>")
TWIN_REFUSAL_PHRASES: Final = ("reactivate refused for", "({slug})", "live_twin_exists")
TWIN_EXIT_STATUS: Final = 1
RESTORE_ALLOWED: Final = (items.ROADMAP_UPDATED_AT,)

DETAIL_PRESENT: Final = "{slug} already exists on a read path: {slugs!r}"
DETAIL_REMOVED_NODE: Final = "{when}: `todo list --removed-only` holds {found!r}, not exactly one node for {slug}"
DETAIL_NODE_FIELD: Final = "{when}: the removed node reads {path} {found!r}, not {expected!r}"
DETAIL_READ_PATH: Final = "{when}: the removed item is still on a default read path ({where})"
DETAIL_RETAINED: Final = "{when}: {path} is {found!r}, not {expected!r} (the removal must retain it)"
DETAIL_ARTIFACT_READ: Final = (
    "`telec todo artifacts read {slug} {name}` exited {status} with {output!r}, not the retained body"
)
DETAIL_REFUSAL: Final = "{case}: the output lacks {needle!r} or the exit status is wrong ({status}): {output!r}"
DETAIL_REMOVED_ABSENT: Final = "{when}: the removed item {slug} is not found by `show --include-removed`"
DETAIL_RESTORE: Final = "`telec todo reactivate {slug}` exited {status} without {phrase!r}: {output!r}"
DETAIL_STILL_REMOVED: Final = "{when}: {slug} is still listed as removed"
DETAIL_NOT_LISTED: Final = "{when}: {slug} is not in the default listing"
DETAIL_TWIN_REMOVED_AT: Final = "the twin refusal changed the removed node's removed_at from {before!r} to {after!r}"
DETAIL_WIDE_SET: Final = "{when}: the wide slug set (removed included) no longer holds {slug}"
DETAIL_RESTORED_SLUGS: Final = "the slugs after the restoration are {after!r}, not those before the removal {before!r}"


def _removed_node(observer: Observer, when: str) -> Mapping[str, object]:
    nodes = [node for node in items.removed_nodes(observer) if node.get(items.FIELD_SLUG) == SLUG]
    if len(nodes) != 1:
        raise creation.platform_failure(DETAIL_REMOVED_NODE.format(when=when, found=nodes, slug=SLUG))
    return nodes[0]


def _remove(observer: Observer) -> None:
    outcome = observer.run((items.TELEC, items.TODO, items.REMOVE, SLUG))
    items.completed_operation(observer, f"todo remove {SLUG}", outcome.output, outcome.exit_status)


def _require_removed(observer: Observer, baseline: SessionView, when: str) -> Mapping[str, object]:
    """Step 1 after the operation: the item left every default read path and sits in the removed list."""
    if observer.show(SLUG) is not None:
        raise creation.platform_failure(DETAIL_READ_PATH.format(when=when, where="todo show"))
    if SLUG in items.listing_slugs(observer):
        raise creation.platform_failure(DETAIL_READ_PATH.format(when=when, where="todo list"))
    node = _removed_node(observer, when)
    if node.get(items.FIELD_STATUS) != items.STATUS_REMOVED:
        raise creation.platform_failure(
            DETAIL_NODE_FIELD.format(
                when=when, path="status", found=node.get(items.FIELD_STATUS), expected=items.STATUS_REMOVED
            )
        )
    removed_at = node.get(items.FIELD_REMOVED_AT)
    if not isinstance(removed_at, str) or not removed_at:
        raise creation.platform_failure(
            DETAIL_NODE_FIELD.format(when=when, path=items.FIELD_REMOVED_AT, found=removed_at, expected="non-empty")
        )
    if SLUG not in observer.slugs(retain=False):
        raise creation.platform_failure(DETAIL_WIDE_SET.format(when=when, slug=SLUG))
    creation.require_sessions_equal(baseline, observer.sessions(retain=False), when)
    return node


def _retained(observer: Observer, original: Mapping[str, object], baseline: SessionView) -> None:
    """Step 2: the retained content stays readable and a removed item accepts no other change."""
    when = "while removed"
    shown = items.show_removed(observer, SLUG)
    if shown is None:
        raise creation.platform_failure(DETAIL_REMOVED_ABSENT.format(when=when, slug=SLUG))
    _, expected = creation.dig(original, f"{creation.FIELD_ARTIFACT_CONTENT}.{INPUT}")
    for path, want in (
        (f"{creation.FIELD_ARTIFACT_CONTENT}.{INPUT}", expected),
        (f"{creation.FIELD_STATE}.{creation.FIELD_PHASE}", PHASE_PREPARATION),
    ):
        found, value = creation.dig(shown, path)
        if not found:
            raise creation.trace_failure(creation.DETAIL_PATH_ABSENT.format(slug=SLUG, path=path))
        if value != want:
            raise creation.platform_failure(DETAIL_RETAINED.format(when=when, path=path, found=value, expected=want))
    _, artifacts = creation.dig(shown, creation.FIELD_ARTIFACTS)
    if not isinstance(artifacts, list) or INPUT not in artifacts:
        raise creation.platform_failure(
            DETAIL_RETAINED.format(
                when=when, path=creation.FIELD_ARTIFACTS, found=artifacts, expected=f"contains {INPUT}"
            )
        )
    read = observer.run((items.TELEC, items.TODO, ARTIFACTS, READ, SLUG, INPUT))
    body = str(expected).strip()
    if read.exit_status != 0 or read.output.replace("\r\n", "\n").strip() != body:
        raise creation.platform_failure(
            DETAIL_ARTIFACT_READ.format(slug=SLUG, name=INPUT, status=read.exit_status, output=read.output[-300:])
        )
    refused = observer.run(
        (items.TELEC, items.TODO, items.UPDATE, SLUG, items.HOLD_FLAG, items.REASON_OPTION, REASON_REFUSED)
    )
    for needle in (phrase.format(slug=SLUG) for phrase in UPDATE_REFUSAL_PHRASES):
        if needle not in refused.output:
            raise creation.platform_failure(
                DETAIL_REFUSAL.format(
                    case="update of a removed item",
                    needle=needle,
                    status=refused.exit_status,
                    output=refused.output[-300:],
                )
            )
    if refused.exit_status in (0, None):
        raise creation.platform_failure(
            DETAIL_REFUSAL.format(
                case="update of a removed item",
                needle="non-zero exit",
                status=refused.exit_status,
                output=refused.output[-300:],
            )
        )
    payload_work.sleep(items.SETTLE_SECONDS)
    later = items.show_removed(observer, SLUG)
    if later is None or creation.differences(shown, later):
        raise creation.platform_failure(
            DETAIL_REMOVED_ABSENT.format(when="after the refused update", slug=SLUG)
            if later is None
            else items.DETAIL_WRITE.format(
                case="refused update", when="five seconds later", paths=creation.differences(shown, later)
            )
        )
    creation.require_value(SLUG, later, f"{creation.FIELD_STATE}.{creation.FIELD_HOLD}", False)
    if observer.show(SLUG, retain=False) is not None:
        raise creation.platform_failure(DETAIL_READ_PATH.format(when="after the refused update", where="todo show"))
    creation.require_sessions_equal(baseline, observer.sessions(retain=False), "after the refused update")


def _restore(observer: Observer, original: Mapping[str, object], baseline: SessionView, slugs_before: set[str]) -> None:
    """Step 3: the restoration returns the item as the same record in preparation, with no episode."""
    outcome = observer.run((items.TELEC, items.TODO, items.REACTIVATE, SLUG))
    phrase = RESTORED_PHRASE.format(slug=SLUG)
    if outcome.exit_status != 0 or phrase not in outcome.output:
        raise creation.platform_failure(
            DETAIL_RESTORE.format(slug=SLUG, status=outcome.exit_status, phrase=phrase, output=outcome.output[-300:])
        )
    restored = observer.show(SLUG)
    if restored is None:
        raise creation.platform_failure(items.DETAIL_ABSENT.format(case="R5 restoration", when="after the restoration"))
    creation.require_value(SLUG, restored, f"{creation.FIELD_STATE}.{creation.FIELD_PHASE}", PHASE_PREPARATION)
    creation.require_value(SLUG, restored, f"{creation.FIELD_ROADMAP}.{creation.FIELD_STATUS}", creation.STATUS_ACTIVE)
    creation.require_value(SLUG, restored, f"{creation.FIELD_STATE}.{creation.FIELD_HOLD}", False)
    creation.require_value(
        SLUG, restored, f"{creation.FIELD_STANDING}.{creation.FIELD_STANDING_PHASE}", PHASE_PREPARATION
    )
    creation.require_unclaimed(SLUG, restored)
    creation.require_standing_clear(SLUG, restored)
    items.require_only_changes("R5 restoration", original, restored, RESTORE_ALLOWED)
    if any(node.get(items.FIELD_SLUG) == SLUG for node in items.removed_nodes(observer)):
        raise creation.platform_failure(DETAIL_STILL_REMOVED.format(when="after the restoration", slug=SLUG))
    if SLUG not in items.listing_slugs(observer):
        raise creation.platform_failure(DETAIL_NOT_LISTED.format(when="after the restoration", slug=SLUG))
    creation.require_sessions_equal(baseline, observer.sessions(retain=False), "after the restoration")
    after = observer.slugs(retain=False)
    if after != slugs_before:
        raise creation.platform_failure(DETAIL_RESTORED_SLUGS.format(after=sorted(after), before=sorted(slugs_before)))


def _live_twin(observer: Observer, baseline: SessionView) -> None:
    """Step 4: a live twin blocks the restoration and is not disturbed."""
    _remove(observer)
    twin = creation.create_item(observer, SLUG, CONTENT_TWIN, KIND_FEATURE, approved=True)
    creation.require_created(twin, SLUG)
    shown = observer.show(SLUG)
    if shown is None:
        raise creation.platform_failure(items.DETAIL_ABSENT.format(case="R5 live twin", when="after its creation"))
    creation.require_value(
        SLUG,
        shown,
        f"{creation.FIELD_ARTIFACT_CONTENT}.{INPUT}",
        creation.INPUT_BODY.format(slug=SLUG, content=CONTENT_TWIN),
    )
    node = _removed_node(observer, "before the twin refusal")
    refused = observer.run((items.TELEC, items.TODO, items.REACTIVATE, SLUG))
    for needle in (phrase.format(slug=SLUG) for phrase in TWIN_REFUSAL_PHRASES):
        if needle not in refused.output:
            raise creation.platform_failure(
                DETAIL_REFUSAL.format(
                    case="reactivate over a live twin",
                    needle=needle,
                    status=refused.exit_status,
                    output=refused.output[-300:],
                )
            )
    if refused.exit_status != TWIN_EXIT_STATUS:
        raise creation.platform_failure(
            DETAIL_REFUSAL.format(
                case="reactivate over a live twin",
                needle=f"exit {TWIN_EXIT_STATUS}",
                status=refused.exit_status,
                output=refused.output[-300:],
            )
        )
    sessions = observer.sessions(retain=False)
    items.require_nothing_written(observer, SLUG, "R5 live twin refusal", shown, sessions)
    after = _removed_node(observer, "after the twin refusal")
    if after.get(items.FIELD_REMOVED_AT) != node.get(items.FIELD_REMOVED_AT):
        raise creation.platform_failure(
            DETAIL_TWIN_REMOVED_AT.format(
                before=node.get(items.FIELD_REMOVED_AT), after=after.get(items.FIELD_REMOVED_AT)
            )
        )
    creation.require_sessions_equal(baseline, observer.sessions(retain=False), "after the twin refusal")


def run_removal(host: FoundationHost, project: Path, source_root: Path) -> None:
    """Journey R5; raises JourneyFailure leading with its class."""
    observer = Observer(host)
    creation.require_manual_runner(observer)
    creation.enter_project(observer, project)
    try:
        present = observer.slugs()
        if SLUG in present:
            raise creation.binding_failure(DETAIL_PRESENT.format(slug=SLUG, slugs=sorted(present)))
        baseline = observer.sessions()
        creation.require_created(creation.create_item(observer, SLUG, CONTENT, KIND_FEATURE, approved=True), SLUG)
        original = items.quiescent(observer, SLUG, "R5 item")
        creation.require_value(
            SLUG,
            original,
            f"{creation.FIELD_ARTIFACT_CONTENT}.{INPUT}",
            creation.INPUT_BODY.format(slug=SLUG, content=CONTENT),
        )
        slugs_before = observer.slugs()
        _remove(observer)
        _require_removed(observer, baseline, "after the removal")
        _retained(observer, original, baseline)
        _restore(observer, original, baseline, slugs_before)
        _live_twin(observer, baseline)
    finally:
        creation.leave_project(observer, source_root)
