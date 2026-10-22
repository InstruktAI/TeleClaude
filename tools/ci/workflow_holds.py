"""Journey R3 of the workflow acceptance: the public hold and release, with no phase override.

The journey\'s assertions are the independently reviewed ones recorded in the shared handoff workspace
(`journeys/r2-r3-r5-assertion-draft.md`, section 3, approved at exact SHA-256
8055cc9cf4741c32e655e52dea679087e7ded6fbe9c40f715debbf1c382c9ceb; authority the pending
`local/projects/teleclaude/spec/feature/workflow/item-lifecycle` Hold and `.../todo-creation` create-time brake).
It proves that `telec todo update --hold --reason` sets the brake and only the brake, that the brake is durable, that
`--release` clears it and only it, that the create-time brake carries the creation source, and that no session is
started. Hold and release are synchronous public writes: their JSON answer and an immediate independent `show`
projection are what is verified. The usage gates are labelled as the CLI\'s own and write nothing.

Every observation is a public CLI command through a fresh process on the authenticated owner terminal; the controller
imports no application module and creates no record, identity or authentication state.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from tools.ci import workflow_creation as creation
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_items as items
from tools.ci.workflow_creation import Observer, SessionView
from tools.ci.workflow_foundation import FoundationHost, Outcome

SLUG_HOLD: Final = "ra-hold"
SLUG_CREATE_HOLD: Final = "ra-chold"
SLUGS: Final = (SLUG_HOLD, SLUG_CREATE_HOLD)
CONTENT_HOLD: Final = "r3 hold content"
CONTENT_CREATE_HOLD: Final = "r3 create hold content"
REASON: Final = "r3 brake"
REASON_CREATE: Final = "r3 create brake"
REASON_USAGE: Final = "r3 reason"
KIND_FEATURE: Final = "feature"
PHASE_PREPARATION: Final = "preparation"

STATE_HOLD: Final = "state.hold"
STATE_AUDIT: Final = "state.hold_audit"
AUDIT_SOURCE_MANUAL: Final = "manual"
AUDIT_SOURCE_CREATION: Final = "creation"
EMPTY_AUDIT: Final = {"source": "", "set_at": "", "set_by_session_id": "", "reason": ""}
HOLD_ALLOWED: Final = (STATE_HOLD, STATE_AUDIT, items.ROADMAP_UPDATED_AT)
RELEASE_ALLOWED: Final = (items.ROADMAP_UPDATED_AT,)
ANSWER_STATUS: Final = "ok"
OPERATION_MARKER: Final = "operation_id"
USAGE_GATES: Final = (
    ("U1", (items.HOLD_FLAG,), "--reason is required with --hold"),
    ("U2", (items.REASON_OPTION, REASON_USAGE), "--reason is valid only with --hold"),
    (
        "U3",
        (items.HOLD_FLAG, items.RELEASE_FLAG, items.REASON_OPTION, REASON_USAGE),
        "--hold and --release are mutually exclusive",
    ),
)

DETAIL_PRESENT: Final = "R3 slugs already exist: {found!r}"
DETAIL_PRECONDITION: Final = "{slug}: {path} is {found!r}, not the tested table row"
DETAIL_USAGE: Final = "{case}: the usage gate did not print {phrase!r} with a non-zero exit: exit {status}, {output!r}"
DETAIL_USAGE_RECEIPT: Final = "{case}: a usage gate printed an operation receipt: {output!r}"
DETAIL_ANSWER: Final = "`{command}` answered {output!r}, not status ok for {slug} with hold {hold!r}"
DETAIL_AUDIT: Final = "{slug}: {path} is {found!r}, not {expected!r}"
DETAIL_SESSION_ID: Final = "{slug}: hold_audit.set_by_session_id is {found!r}; the owner terminal has no session"
DETAIL_STANDING_HELD: Final = "{slug}: standing carries held_by {found!r}; a brake is not a claim"
DETAIL_NOT_DURABLE: Final = "{slug}: the item five seconds after the write differs from the write's own read at {paths}"
DETAIL_SLUGS: Final = "the set of slugs changed during the hold step from {before!r} to {after!r}"
DETAIL_AUDIT_SHAPE: Final = "{slug}: hold_audit is not an object: {found!r}"

CONTROL_TERMINAL: Final = "the owner terminal"


def _update(observer: Observer, slug: str, *flags: str) -> Outcome:
    return observer.run((items.TELEC, items.TODO, items.UPDATE, slug, *flags))


def _precondition(slug: str, payload: Mapping[str, object]) -> None:
    for path, expected in (
        (f"{creation.FIELD_STATE}.{creation.FIELD_PHASE}", PHASE_PREPARATION),
        (STATE_HOLD, False),
        (f"{creation.FIELD_STANDING}.{creation.FIELD_STANDING_PHASE}", PHASE_PREPARATION),
    ):
        found, value = creation.dig(payload, path)
        if not found or value != expected:
            raise creation.binding_failure(DETAIL_PRECONDITION.format(slug=slug, path=path, found=value))
    found, runner = creation.dig(payload, f"{creation.FIELD_STATE}.{creation.FIELD_RUNNER}")
    if not found or runner not in (None, creation.EMPTY):
        raise creation.binding_failure(DETAIL_PRECONDITION.format(slug=slug, path=creation.FIELD_RUNNER, found=runner))


def _answer(command: str, slug: str, outcome: Outcome, hold: bool) -> None:
    answer = foundation.json_object(outcome.output)
    if (
        outcome.exit_status != 0
        or answer is None
        or answer.get("status") != ANSWER_STATUS
        or answer.get(items.FIELD_SLUG) != slug
        or answer.get("hold") is not hold
    ):
        raise creation.platform_failure(
            DETAIL_ANSWER.format(command=command, output=outcome.output[-300:], slug=slug, hold=hold)
        )


def _usage_gates(observer: Observer, baseline: SessionView, before: Mapping[str, object]) -> None:
    for case, flags, phrase in USAGE_GATES:
        outcome = _update(observer, SLUG_HOLD, *flags)
        if outcome.exit_status in (0, None) or phrase not in creation.normalized(outcome.output):
            raise creation.fail(
                creation.CLASS_GATE,
                DETAIL_USAGE.format(case=case, phrase=phrase, status=outcome.exit_status, output=outcome.output[-300:]),
            )
        if OPERATION_MARKER in outcome.output:
            raise creation.platform_failure(DETAIL_USAGE_RECEIPT.format(case=case, output=outcome.output[-300:]))
        items.require_nothing_written(observer, SLUG_HOLD, case, before, baseline)


def _held_projection(slug: str, payload: Mapping[str, object], reason: str, source: str) -> None:
    creation.require_value(slug, payload, STATE_HOLD, True)
    for path, expected in ((f"{STATE_AUDIT}.reason", reason), (f"{STATE_AUDIT}.source", source)):
        creation.require_value(slug, payload, path, expected)
    found, set_at = creation.dig(payload, f"{STATE_AUDIT}.set_at")
    if not found:
        raise creation.trace_failure(creation.DETAIL_PATH_ABSENT.format(slug=slug, path=f"{STATE_AUDIT}.set_at"))
    if not isinstance(set_at, str) or not set_at:
        raise creation.platform_failure(
            DETAIL_AUDIT.format(slug=slug, path="hold_audit.set_at", found=set_at, expected="non-empty")
        )
    creation.require_value(slug, payload, f"{creation.FIELD_STATE}.{creation.FIELD_PHASE}", PHASE_PREPARATION)
    creation.require_value(
        slug, payload, f"{creation.FIELD_STANDING}.{creation.FIELD_STANDING_PHASE}", PHASE_PREPARATION
    )
    _, standing = creation.dig(payload, creation.FIELD_STANDING)
    if isinstance(standing, Mapping) and "held_by" in standing:
        raise creation.platform_failure(DETAIL_STANDING_HELD.format(slug=slug, found=standing["held_by"]))
    creation.require_unclaimed(slug, payload)


def _released_projection(slug: str, payload: Mapping[str, object]) -> None:
    creation.require_value(slug, payload, STATE_HOLD, False)
    found, audit = creation.dig(payload, STATE_AUDIT)
    if not found:
        raise creation.trace_failure(creation.DETAIL_PATH_ABSENT.format(slug=slug, path=STATE_AUDIT))
    if not isinstance(audit, Mapping):
        raise creation.trace_failure(DETAIL_AUDIT_SHAPE.format(slug=slug, found=audit))
    if dict(audit) != EMPTY_AUDIT:
        raise creation.platform_failure(
            DETAIL_AUDIT.format(slug=slug, path=STATE_AUDIT, found=dict(audit), expected=EMPTY_AUDIT)
        )


def _hold_and_release(observer: Observer, baseline: SessionView, quiet: Mapping[str, object]) -> None:
    """Steps 1 to 3: the brake and only the brake, durable, then its release."""
    slugs = observer.slugs()
    held = _update(observer, SLUG_HOLD, items.HOLD_FLAG, items.REASON_OPTION, REASON)
    _answer("todo update --hold", SLUG_HOLD, held, True)
    first = observer.show(SLUG_HOLD)
    if first is None:
        raise creation.platform_failure(items.DETAIL_ABSENT.format(case="R3 hold", when="after the hold"))
    _held_projection(SLUG_HOLD, first, REASON, AUDIT_SOURCE_MANUAL)
    found, session_id = creation.dig(first, f"{STATE_AUDIT}.set_by_session_id")
    if not found:
        raise creation.trace_failure(
            creation.DETAIL_PATH_ABSENT.format(slug=SLUG_HOLD, path=f"{STATE_AUDIT}.set_by_session_id")
        )
    if session_id != creation.EMPTY:
        raise creation.trace_failure(DETAIL_SESSION_ID.format(slug=SLUG_HOLD, found=session_id))
    items.require_only_changes("R3 hold", quiet, first, HOLD_ALLOWED)
    creation.require_sessions_equal(baseline, observer.sessions(retain=False), "after the hold")
    if observer.slugs(retain=False) != slugs:
        raise creation.platform_failure(
            DETAIL_SLUGS.format(before=sorted(slugs), after=sorted(observer.slugs(retain=False)))
        )
    time.sleep(items.SETTLE_SECONDS)
    later = observer.show(SLUG_HOLD, retain=False)
    paths = creation.differences(first, later) if later is not None else ["absent"]
    if paths:
        raise creation.platform_failure(DETAIL_NOT_DURABLE.format(slug=SLUG_HOLD, paths=paths))
    released = _update(observer, SLUG_HOLD, items.RELEASE_FLAG)
    _answer("todo update --release", SLUG_HOLD, released, False)
    second = observer.show(SLUG_HOLD)
    if second is None:
        raise creation.platform_failure(items.DETAIL_ABSENT.format(case="R3 release", when="after the release"))
    _released_projection(SLUG_HOLD, second)
    items.require_only_changes("R3 release", quiet, second, RELEASE_ALLOWED)
    creation.require_sessions_equal(baseline, observer.sessions(retain=False), "after the release")


def _create_time_brake(observer: Observer) -> None:
    """Step 4: the create-time brake carries the creation source, leaves the item active, and releases the same way."""
    slug = SLUG_CREATE_HOLD
    argv = (
        items.TELEC,
        items.TODO,
        items.CREATE,
        slug,
        CONTENT_CREATE_HOLD,
        items.KIND_OPTION,
        KIND_FEATURE,
        items.APPROVED_FLAG,
        items.HOLD_FLAG,
        items.REASON_OPTION,
        REASON_CREATE,
    )
    creation.require_created(observer.run(argv), slug)
    payload = observer.show(slug)
    if payload is None:
        raise creation.platform_failure(items.DETAIL_ABSENT.format(case="R3 create brake", when="after creation"))
    _held_projection(slug, payload, REASON_CREATE, AUDIT_SOURCE_CREATION)
    creation.require_value(slug, payload, f"{creation.FIELD_ROADMAP}.{creation.FIELD_STATUS}", creation.STATUS_ACTIVE)
    creation.require_value(
        slug,
        payload,
        f"{creation.FIELD_ARTIFACT_CONTENT}.{creation.INPUT_ARTIFACT}",
        creation.INPUT_BODY.format(slug=slug, content=CONTENT_CREATE_HOLD),
    )
    released = _update(observer, slug, items.RELEASE_FLAG)
    _answer("todo update --release", slug, released, False)
    after = observer.show(slug)
    if after is None:
        raise creation.platform_failure(items.DETAIL_ABSENT.format(case="R3 create release", when="after the release"))
    _released_projection(slug, after)


def run_holds(host: FoundationHost, project: Path, source_root: Path) -> None:
    """Journey R3; raises JourneyFailure leading with its class."""
    observer = Observer(host)
    creation.require_manual_runner(observer)
    creation.enter_project(observer, project)
    try:
        present = observer.slugs().intersection(SLUGS)
        if present:
            raise creation.binding_failure(DETAIL_PRESENT.format(found=sorted(present)))
        creation.require_created(
            creation.create_item(observer, SLUG_HOLD, CONTENT_HOLD, KIND_FEATURE, approved=True), SLUG_HOLD
        )
        quiet = items.quiescent(observer, SLUG_HOLD, "R3 hold item")
        _precondition(SLUG_HOLD, quiet)
        baseline = observer.sessions()
        _usage_gates(observer, baseline, quiet)
        _hold_and_release(observer, baseline, quiet)
        _create_time_brake(observer)
        creation.absence_window(observer, baseline, SLUGS)
    finally:
        creation.leave_project(observer, source_root)
