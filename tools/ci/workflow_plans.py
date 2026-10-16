"""Journey R2 of the workflow acceptance: plan creation and the task lane outside the v2 machine.

The journey\'s assertions are the independently reviewed ones recorded in the shared handoff workspace
(`journeys/r2-r3-r5-assertion-draft.md`, section 2, approved at exact SHA-256
8055cc9cf4741c32e655e52dea679087e7ded6fbe9c40f715debbf1c382c9ceb; authority the pending
`local/projects/teleclaude/spec/feature/workflow/todo-creation`, `.../item-lifecycle` and `sdlc/spec/todo-kind-task`
contracts of issue 128). It proves that `--plan` seeds a change that stays in preparation with its plan artifact, that
the flag is rejected for a feature and a bug before any write, that a bare task enters its own lane with no standing,
that a task created with its plan is pre-authorized by construction, that no session is started, and that the legacy
task stamp is still the task lane\'s own refusal and writes nothing. It runs no entry verb, claim or act on any task.

Every observation is a public CLI command through a fresh process on the authenticated owner terminal; the controller
imports no application module and creates no record, identity or authentication state.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final

from tools.ci import workflow_creation as creation
from tools.ci import workflow_items as items
from tools.ci import workflow_publication as publication
from tools.ci.workflow_creation import Observer, SessionView
from tools.ci.workflow_foundation import FoundationHost, Outcome

SLUG_PLAN: Final = "ra-plan"
SLUG_FEATURE_PLAN: Final = "ra-featplan"
SLUG_BUG_PLAN: Final = "ra-bugplan"
SLUG_TASK: Final = "ra-task"
SLUG_TASK_PLAN: Final = "ra-taskplan"
SLUGS: Final = (SLUG_PLAN, SLUG_FEATURE_PLAN, SLUG_BUG_PLAN, SLUG_TASK, SLUG_TASK_PLAN)
CONTENT_PLAN: Final = "r2 change plan content"
CONTENT_TASK: Final = "r2 task input content"
CONTENT_TASK_PLAN: Final = "r2 task plan content"
CONTENT_FEATURE: Final = "r2 feature control content"
CONTENT_BUG: Final = "r2 bug control content"
KIND_CHANGE: Final = "change"
KIND_FEATURE: Final = "feature"
KIND_BUG: Final = "bug"
KIND_TASK: Final = "task"

ARTIFACT_PLAN: Final = "implementation-plan"
ARTIFACT_TASK_PLAN: Final = "task-plan"
ARTIFACT_INPUT: Final = "input"
PLAN_BODY: Final = "# {slug} — Implementation Plan\n\n{content}\n"
TASK_PLAN_BODY: Final = "# {slug} — Task Plan\n\n{content}\n"
INPUT_BODY: Final = "# {slug} — Input\n\n{content}\n"
PHASE_PREPARATION: Final = "preparation"
PHASE_TASK_DRAFTING: Final = "task_plan_drafting"
PHASE_PREPARED: Final = "prepared"
STANDING: Final = "standing"
STANDING_NONE_OF: Final = ("held_by", "admitted", "creative_episode", "waiting_on")
APPROVAL_PATH: Final = "approvals.task_approved"
STAMP: Final = "stamp"
TASK_APPROVED_FLAG: Final = "--task-approved"
REJECTION_PHRASES: Final = ("--plan", "valid only", "--kind change", "--kind task")
STAMP_PHRASE: Final = "cannot stamp task_approved: task is not prepared"
STAMP_FORBIDDEN: Final = ("Door:", "is refused:")
ABSENCE_LABEL: Final = "after the task and plan creations"

DETAIL_ARTIFACTS: Final = "{slug}: artifacts {found!r} do not contain {name!r}"
DETAIL_STANDING_KEY: Final = "{slug}: standing carries {key!r}, which a supplied plan alone does not give"
DETAIL_SEEDED: Final = "{slug}: artifact_state.{name}.seeded is {found!r}, not True"
DETAIL_REJECTION: Final = "{slug}: the rejected `--plan` {problem}: exit {status}, {output!r}"
DETAIL_STANDING_PRESENT: Final = "{slug}: a task carries a standing block {found!r}; the task lane has none"
DETAIL_APPROVAL_EARLY: Final = "{slug}: a bare task already shows an approved task_approved stamp: {found!r}"
DETAIL_DIGEST: Final = "{slug}: approved_digest {digest!r} is not the task-plan digest {expected!r}"
DETAIL_STAMP_GATE: Final = "the legacy task stamp did not reach its own refusal: exit {status}, {output!r}"
DETAIL_STAMP_V2: Final = "the legacy task stamp was refused by the v2 machine: {output!r}"
DETAIL_STAMP_EXIT: Final = "the legacy task stamp exited {status}, not non-zero: {output!r}"
LOG_TERMS: Final = ("Traceback", "ERROR", "exception", "todo creation", "500")
DETAIL_CREATE_LOGS: Final = "{error} (daemon logs: {logs})"
DETAIL_PRESENT: Final = "R2 slugs already exist: {found!r}"


def _create(observer: Observer, slug: str, content: str, kind: str, *, plan: bool) -> Outcome:
    argv = [items.TELEC, items.TODO, items.CREATE, slug, content, items.KIND_OPTION, kind]
    if plan:
        argv.append(items.PLAN_FLAG)
    argv.append(items.APPROVED_FLAG)
    return observer.run(argv)


def _created(observer: Observer, slug: str, content: str, kind: str, *, plan: bool) -> None:
    """A creation that must succeed; a failure carries the daemon's log text, which a failed case alone can keep."""
    outcome = _create(observer, slug, content, kind, plan=plan)
    try:
        creation.require_created(outcome, slug)
    except creation.JourneyFailure as failure:
        logs = publication.log_evidence(observer.host, LOG_TERMS)
        raise creation.JourneyFailure(DETAIL_CREATE_LOGS.format(error=failure, logs=logs)) from failure


def _shown(observer: Observer, slug: str) -> Mapping[str, object]:
    payload = observer.show(slug)
    if payload is None:
        raise creation.platform_failure(
            creation.DETAIL_VALUE.format(slug=slug, path="existence", found="absent", expected="present")
        )
    return payload


def _artifacts(slug: str, payload: Mapping[str, object], name: str) -> None:
    _, artifacts = creation.dig(payload, creation.FIELD_ARTIFACTS)
    if not isinstance(artifacts, list) or not all(isinstance(entry, str) for entry in artifacts):
        raise creation.trace_failure(creation.DETAIL_ARTIFACT_SHAPE.format(slug=slug, found=artifacts))
    if name not in artifacts:
        raise creation.platform_failure(DETAIL_ARTIFACTS.format(slug=slug, found=artifacts, name=name))


def _common(slug: str, payload: Mapping[str, object], kind: str, phase: str) -> None:
    creation.require_value(slug, payload, f"{creation.FIELD_STATE}.{creation.FIELD_KIND}", kind)
    creation.require_value(slug, payload, f"{creation.FIELD_STATE}.{creation.FIELD_PHASE}", phase)
    creation.require_value(slug, payload, f"{creation.FIELD_ROADMAP}.{creation.FIELD_STATUS}", creation.STATUS_ACTIVE)
    creation.require_value(slug, payload, f"{creation.FIELD_STATE}.{creation.FIELD_HOLD}", False)
    creation.require_unclaimed(slug, payload)


def _no_standing(slug: str, payload: Mapping[str, object]) -> None:
    if STANDING in payload:
        raise creation.platform_failure(DETAIL_STANDING_PRESENT.format(slug=slug, found=payload[STANDING]))


def _plan_creation(observer: Observer) -> None:
    """Step 1: a plan seeds a change that stays in preparation."""
    slug = SLUG_PLAN
    _created(observer, slug, CONTENT_PLAN, KIND_CHANGE, plan=True)
    payload = _shown(observer, slug)
    _common(slug, payload, KIND_CHANGE, PHASE_PREPARATION)
    creation.require_value(slug, payload, f"{STANDING}.{creation.FIELD_STANDING_PHASE}", PHASE_PREPARATION)
    _artifacts(slug, payload, ARTIFACT_PLAN)
    creation.require_value(
        slug,
        payload,
        f"{creation.FIELD_ARTIFACT_CONTENT}.{ARTIFACT_PLAN}",
        PLAN_BODY.format(slug=slug, content=CONTENT_PLAN),
    )
    _, standing = creation.dig(payload, STANDING)
    if not isinstance(standing, Mapping):
        raise creation.trace_failure(creation.DETAIL_PATH_ABSENT.format(slug=slug, path=STANDING))
    for key in STANDING_NONE_OF:
        if key in standing:
            raise creation.platform_failure(DETAIL_STANDING_KEY.format(slug=slug, key=key))
    found, seeded = creation.dig(payload, f"artifact_state.{ARTIFACT_PLAN}.seeded")
    if not found:
        raise creation.trace_failure(
            creation.DETAIL_PATH_ABSENT.format(slug=slug, path=f"artifact_state.{ARTIFACT_PLAN}.seeded")
        )
    if seeded is not True:
        raise creation.platform_failure(DETAIL_SEEDED.format(slug=slug, name=ARTIFACT_PLAN, found=seeded))


def _plan_rejection(observer: Observer, baseline: SessionView) -> None:
    """Step 2: `--plan` is rejected for a feature and a bug, before any write."""
    for slug, kind, content in (
        (SLUG_FEATURE_PLAN, KIND_FEATURE, CONTENT_FEATURE),
        (SLUG_BUG_PLAN, KIND_BUG, CONTENT_BUG),
    ):
        outcome = _create(observer, slug, content, kind, plan=True)
        if outcome.exit_status in (0, None):
            raise creation.platform_failure(
                DETAIL_REJECTION.format(
                    slug=slug, problem="was accepted", status=outcome.exit_status, output=outcome.output[-300:]
                )
            )
        missing = [phrase for phrase in REJECTION_PHRASES if phrase not in outcome.output]
        if missing:
            raise creation.platform_failure(
                DETAIL_REJECTION.format(
                    slug=slug,
                    problem=f"does not name {missing!r}",
                    status=outcome.exit_status,
                    output=outcome.output[-300:],
                )
            )
        items.require_absent_everywhere(observer, [slug], baseline, "the rejected --plan")


def _plain_twins(observer: Observer) -> None:
    """Step 3: the rejection is the flag\'s: the same operands without it create in preparation."""
    for slug, kind, content in (
        (SLUG_FEATURE_PLAN, KIND_FEATURE, CONTENT_FEATURE),
        (SLUG_BUG_PLAN, KIND_BUG, CONTENT_BUG),
    ):
        _created(observer, slug, content, kind, plan=False)
        creation.require_value(
            slug, _shown(observer, slug), f"{creation.FIELD_STATE}.{creation.FIELD_PHASE}", PHASE_PREPARATION
        )


def _bare_task(observer: Observer) -> None:
    """Step 4: a bare task enters its own lane, with no standing and no authorization."""
    slug = SLUG_TASK
    _created(observer, slug, CONTENT_TASK, KIND_TASK, plan=False)
    payload = _shown(observer, slug)
    _common(slug, payload, KIND_TASK, PHASE_TASK_DRAFTING)
    _artifacts(slug, payload, ARTIFACT_INPUT)
    creation.require_value(
        slug,
        payload,
        f"{creation.FIELD_ARTIFACT_CONTENT}.{ARTIFACT_INPUT}",
        INPUT_BODY.format(slug=slug, content=CONTENT_TASK),
    )
    _no_standing(slug, payload)
    found, approved = creation.dig(payload, f"{APPROVAL_PATH}.approved")
    if found and approved is True:
        raise creation.platform_failure(DETAIL_APPROVAL_EARLY.format(slug=slug, found=approved))


def _task_with_plan(observer: Observer) -> None:
    """Step 5: a task with its plan is pre-authorized by construction, with the manual runner re-read first."""
    creation.require_manual_runner(observer)
    slug = SLUG_TASK_PLAN
    _created(observer, slug, CONTENT_TASK_PLAN, KIND_TASK, plan=True)
    payload = _shown(observer, slug)
    creation.require_value(slug, payload, f"{creation.FIELD_STATE}.{creation.FIELD_KIND}", KIND_TASK)
    creation.require_value(slug, payload, f"{creation.FIELD_STATE}.{creation.FIELD_PHASE}", PHASE_PREPARED)
    _artifacts(slug, payload, ARTIFACT_TASK_PLAN)
    creation.require_value(
        slug,
        payload,
        f"{creation.FIELD_ARTIFACT_CONTENT}.{ARTIFACT_TASK_PLAN}",
        TASK_PLAN_BODY.format(slug=slug, content=CONTENT_TASK_PLAN),
    )
    creation.require_value(slug, payload, f"{APPROVAL_PATH}.approved", True)
    found, digest = creation.dig(payload, f"{APPROVAL_PATH}.approved_digest")
    _, expected = creation.dig(payload, f"artifact_state.{ARTIFACT_TASK_PLAN}.digest")
    if not found:
        raise creation.trace_failure(
            creation.DETAIL_PATH_ABSENT.format(slug=slug, path=f"{APPROVAL_PATH}.approved_digest")
        )
    if not isinstance(digest, str) or not digest or digest != expected:
        raise creation.platform_failure(DETAIL_DIGEST.format(slug=slug, digest=digest, expected=expected))
    _no_standing(slug, payload)


def _legacy_stamp(observer: Observer, baseline: SessionView) -> None:
    """Step 7: the legacy task stamp is the task lane\'s own refusal and writes nothing."""
    before = _shown(observer, SLUG_TASK)
    sessions = observer.sessions()
    outcome = observer.run((items.TELEC, items.TODO, STAMP, SLUG_TASK, TASK_APPROVED_FLAG))
    text = creation.normalized(outcome.output)
    if any(marker in text for marker in STAMP_FORBIDDEN):
        raise creation.platform_failure(DETAIL_STAMP_V2.format(output=outcome.output[-300:]))
    if STAMP_PHRASE not in text:
        raise creation.fail(
            creation.CLASS_GATE, DETAIL_STAMP_GATE.format(status=outcome.exit_status, output=outcome.output[-300:])
        )
    if outcome.exit_status in (0, None):
        raise creation.platform_failure(
            DETAIL_STAMP_EXIT.format(status=outcome.exit_status, output=outcome.output[-300:])
        )
    items.require_nothing_written(observer, SLUG_TASK, "R2 legacy task stamp", before, sessions)
    creation.require_sessions_equal(baseline, observer.sessions(retain=False), "after the legacy task stamp")


def run_plans(host: FoundationHost, project: Path, source_root: Path) -> None:
    """Journey R2; raises JourneyFailure leading with its class."""
    observer = Observer(host)
    creation.require_manual_runner(observer)
    creation.enter_project(observer, project)
    try:
        present = observer.slugs().intersection(SLUGS)
        if present:
            raise creation.binding_failure(DETAIL_PRESENT.format(found=sorted(present)))
        baseline = observer.sessions()
        _plan_creation(observer)
        _plan_rejection(observer, baseline)
        _plain_twins(observer)
        _bare_task(observer)
        _task_with_plan(observer)
        creation.absence_window(observer, baseline, SLUGS)
        _legacy_stamp(observer, baseline)
    finally:
        creation.leave_project(observer, source_root)
