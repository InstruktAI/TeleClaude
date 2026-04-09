"""Work lifecycle machine definition — states with on_enter handlers and shared mappings.

Provides the canonical machine for the full todo lifecycle (prepare + work phases).
Used by mark_phase, the API route, and display layers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.next_machine._types import (
    DOR_READY_THRESHOLD,
    FINDING_ID_PATTERN,
    ItemPhase,
    StateValue,
    default_state,
)
from teleclaude.core.next_machine.git_ops import (
    get_head_commit,
    get_ref_commit,
    get_remote_branch_head,
    has_uncommitted_changes,
    run_git_command,
)
from teleclaude.core.next_machine.state_io import _normalize_finalize_state
from teleclaude.core.next_machine.state_machine import State, StateMachine, TargetContext

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Inline helpers
# ---------------------------------------------------------------------------


def _extract_finding_ids(cwd: str, slug: str) -> list[str]:
    """Extract stable finding IDs (e.g. R1-F1) from review-findings artifact in DB."""
    from teleclaude.core.next_machine.state_io import _get_todos_db_sync  # pylint: disable=import-outside-toplevel

    db = _get_todos_db_sync(cwd)
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        row = conn.execute(
            "SELECT content FROM todo_artifacts WHERE slug = ? AND name = 'review-findings' LIMIT 1",  # guard: raw-sql
            (slug,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return []
    content: str = row[0]
    seen: list[str] = []
    for match in FINDING_ID_PATTERN.findall(content):
        if match not in seen:
            seen.append(match)
    return seen


def _has_artifact_content(cwd: str, slug: str, artifact_name: str) -> bool:
    """Check if a DB artifact has non-trivial content (beyond whitespace and headings)."""
    from teleclaude.core.next_machine.state_io import _get_todos_db_sync  # pylint: disable=import-outside-toplevel

    db = _get_todos_db_sync(cwd)
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        row = conn.execute(
            "SELECT content FROM todo_artifacts WHERE slug = ? AND name = ? LIMIT 1",  # guard: raw-sql
            (slug, artifact_name),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return False
    text = row[0].strip()
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return len(lines) > 0


_QUALITY_CHECKLIST_TEMPLATE = """\
# Quality Checklist: {slug}

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [ ] Requirements implemented according to scope
- [ ] Implementation-plan task checkboxes all `[x]`
- [ ] Tests pass (`make test`)
- [ ] Lint passes (`make lint`)
- [ ] No silent deferrals in implementation plan
- [ ] Code committed
- [ ] User-facing verification evidence recorded
- [ ] Browser-based frontend or web UI changes smoke-tested with Playwright
- [ ] Working tree clean
- [ ] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

- [ ] Requirements traced to implemented behavior
- [ ] Deferrals justified and not hiding required scope
- [ ] Findings written in `review-findings.md`
- [ ] Verdict recorded (APPROVE or REQUEST CHANGES)
- [ ] Critical issues resolved or explicitly blocked
- [ ] Test coverage and regression risk assessed
- [ ] User-facing verification evidence reviewed
- [ ] Browser-based frontend or web UI changes verified with Playwright during review, or gap recorded as a finding

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
"""


# ---------------------------------------------------------------------------
# on_enter handlers
# ---------------------------------------------------------------------------


def _on_enter_build_started(state: dict[str, StateValue], ctx: TargetContext) -> dict[str, StateValue]:
    """Validate preparation prerequisites before starting build.

    This is the entry gate into the work lifecycle. DOR score must meet
    the threshold. Once past this handler, subsequent steps never re-check DOR.
    """
    kind = state.get("kind")
    if kind == "bug":
        return state  # Bug todos skip DOR — they enter work directly

    current_dor = state.get("dor", {})
    if isinstance(current_dor, dict):
        score = current_dor.get("score", 0)
        if isinstance(score, int) and score < DOR_READY_THRESHOLD:
            raise ValueError(
                f"DOR score {score} is below threshold {DOR_READY_THRESHOLD}. Run telec todo prepare {ctx.slug} first."
            )
    return state


def _on_enter_prepared(  # pylint: disable=too-many-locals
    state: dict[str, StateValue], ctx: TargetContext
) -> dict[str, StateValue]:
    """Validate artifacts exist in DB, stamp DOR/grounding/verdicts for work readiness."""
    from teleclaude.core.next_machine.state_io import _get_todos_db_sync  # pylint: disable=import-outside-toplevel

    slug = ctx.slug
    db = _get_todos_db_sync(ctx.project_root)

    kind = state.get("kind")

    # Prepped todos enter pre-prepared with only an implementation-plan — the plan is
    # their sole spec, no requirements artifact exists. Regular todos still require both.
    if kind != "prepped":
        if not _has_artifact_content(ctx.project_root, slug, "requirements"):
            raise ValueError(f"Missing requirements artifact with content for {slug}")

    if not _has_artifact_content(ctx.project_root, slug, "implementation-plan"):
        raise ValueError(f"Missing implementation-plan artifact with content for {slug}")

    # Quality checklist can be generated
    if not _has_artifact_content(ctx.project_root, slug, "quality-checklist"):
        conn = db._sync_conn()  # pylint: disable=protected-access
        try:
            # Write quality-checklist via sync SQL
            import hashlib as _hl  # pylint: disable=import-outside-toplevel
            from datetime import UTC as _UTC  # pylint: disable=import-outside-toplevel,reimported
            from datetime import datetime as _dt  # pylint: disable=import-outside-toplevel,reimported

            checklist_content = _QUALITY_CHECKLIST_TEMPLATE.format(slug=slug)
            _now = _dt.now(_UTC).isoformat()
            _digest = _hl.sha256(checklist_content.encode("utf-8")).hexdigest()
            # Resolve id
            id_row = conn.execute(
                "SELECT id FROM roadmap WHERE slug = ? AND status != 'delivered' LIMIT 1",  # guard: raw-sql
                (slug,),
            ).fetchone()
            row_id = id_row[0] if id_row else slug
            conn.execute(
                "INSERT INTO todo_artifacts "  # guard: raw-sql
                "(id, slug, name, content, digest, updated_by, updated_at) "
                "VALUES (?, ?, 'quality-checklist', ?, ?, 'on_enter_prepared', ?) "
                "ON CONFLICT(id, name) DO UPDATE SET "
                "content = excluded.content, digest = excluded.digest, "
                "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
                (row_id, slug, checklist_content, _digest, _now),
            )
            conn.commit()
        finally:
            conn.close()

    now_iso = ctx.at

    state["phase"] = ItemPhase.PENDING.value

    # DOR
    state["dor"] = {
        "last_assessed_at": now_iso,
        "score": 8,
        "status": "pass",
        "schema_version": 1,
        "blockers": [],
        "actions_taken": {
            "requirements_updated": False,
            "implementation_plan_updated": False,
        },
    }

    # Review verdicts. Prepped todos have no requirements to review — the plan is the
    # sole spec. Mark requirements_review as "skipped" with an explicit reason so
    # downstream consumers and audits can distinguish an intentional skip from a
    # forgotten review.
    if kind == "prepped":
        state["requirements_review"] = {
            "verdict": "skipped",
            "reviewed_at": now_iso,
            "findings_count": 0,
            "reason": "prepped",
        }
    else:
        state["requirements_review"] = {
            "verdict": "approve",
            "reviewed_at": now_iso,
            "findings_count": 0,
        }
    state["plan_review"] = {
        "verdict": "approve",
        "reviewed_at": now_iso,
        "findings_count": 0,
    }

    # Grounding
    rc, current_sha, _ = run_git_command(["rev-parse", "HEAD"], cwd=ctx.project_root)
    if rc != 0 or not current_sha.strip():
        raise ValueError(
            f"git rev-parse HEAD failed (rc={rc}) in {ctx.project_root} — cannot establish grounding baseline"
        )
    grounding: dict[str, StateValue] = {
        **default_state()["grounding"],  # type: ignore[dict-item]
        "valid": True,
        "base_sha": current_sha.strip(),
        "last_grounded_at": now_iso,
        "invalidation_reason": "",
        "changed_paths": [],
    }
    # Read input digest from DB
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        input_row = conn.execute(
            "SELECT digest FROM todo_artifacts WHERE slug = ? AND name = 'input' LIMIT 1",  # guard: raw-sql
            (slug,),
        ).fetchone()
    finally:
        conn.close()
    if input_row and input_row[0]:
        grounding["input_digest"] = input_row[0]
    state["grounding"] = grounding

    return state


def _on_enter_review_changes(state: dict[str, StateValue], ctx: TargetContext) -> dict[str, StateValue]:
    """Bump review_round, stamp baseline, extract finding IDs."""
    review_round = state.get("review_round")
    current_round = review_round if isinstance(review_round, int) else 0
    resolved = state.get("resolved_findings")
    resolved_ids = list(resolved) if isinstance(resolved, list) else []

    state["review_round"] = current_round + 1
    head_sha = get_head_commit(ctx.worktree_path)
    if head_sha:
        state["review_baseline_commit"] = head_sha
    else:
        logger.warning(
            "review_baseline_commit not stamped: get_head_commit returned empty worktree=%s slug=%s",
            ctx.worktree_path,
            ctx.slug,
        )

    findings_ids = _extract_finding_ids(ctx.project_root, ctx.slug)
    state["unresolved_findings"] = findings_ids  # type: ignore[assignment]
    state["resolved_findings"] = list(dict.fromkeys(str(i) for i in resolved_ids))

    return state


def _on_enter_review_approved(state: dict[str, StateValue], ctx: TargetContext) -> dict[str, StateValue]:
    """Bump review_round, stamp baseline, merge findings."""
    review_round = state.get("review_round")
    current_round = review_round if isinstance(review_round, int) else 0
    unresolved = state.get("unresolved_findings")
    unresolved_ids = list(unresolved) if isinstance(unresolved, list) else []
    resolved = state.get("resolved_findings")
    resolved_ids = list(resolved) if isinstance(resolved, list) else []

    state["review_round"] = current_round + 1
    head_sha = get_head_commit(ctx.worktree_path)
    if head_sha:
        state["review_baseline_commit"] = head_sha
    else:
        logger.warning(
            "review_baseline_commit not stamped: get_head_commit returned empty worktree=%s slug=%s",
            ctx.worktree_path,
            ctx.slug,
        )

    merged = list(dict.fromkeys([*(str(i) for i in resolved_ids), *(str(i) for i in unresolved_ids)]))
    state["resolved_findings"] = merged  # type: ignore[assignment]
    state["unresolved_findings"] = []

    return state


def _on_enter_finalize_ready(state: dict[str, StateValue], ctx: TargetContext) -> dict[str, StateValue]:
    """Validate worktree, no uncommitted changes, HEAD matches, write finalize sub-dict."""
    # Guard against regression from finalize_handed_off back to finalize_ready
    finalize = state.get("finalize")
    if isinstance(finalize, dict) and finalize.get("status") == "handed_off":
        raise ValueError(f"cannot regress {ctx.slug} from finalize_handed_off to finalize_ready")

    slug = ctx.slug
    if not Path(ctx.worktree_path).exists():
        raise ValueError(f"worktree not found at {ctx.worktree_path}")
    if has_uncommitted_changes(ctx.project_root, slug):
        raise ValueError(f"worktree for {slug} has uncommitted changes")

    worktree_head = get_head_commit(ctx.worktree_path)
    branch_head = get_ref_commit(ctx.project_root, slug)
    if not worktree_head or not branch_head:
        raise ValueError(f"unable to resolve finalized branch head for {slug}")
    if worktree_head != branch_head:
        raise ValueError(
            f"branch {slug} does not match worktree HEAD after finalize prepare "
            f"(branch={branch_head or '<missing>'}, worktree={worktree_head or '<missing>'})"
        )

    remote_head = get_remote_branch_head(ctx.project_root, slug)
    if not remote_head:
        raise ValueError(f"origin/{slug} is missing — push the finalized branch before marking ready")
    if remote_head != branch_head:
        raise ValueError(
            f"origin/{slug} is at {remote_head}, expected finalized head {branch_head}; "
            "push the latest branch head before marking ready"
        )

    # Idempotency is handled at the engine level: StateMachine.target() returns without calling
    # on_enter when source == target. A second call to mark_phase("finalize_ready") is a no-op
    # at the engine level and this handler is not reached. Repeated calls do NOT re-validate
    # remote/uncommitted state — callers must rely on the initial transition validation.

    now = datetime.now(UTC).isoformat()
    state["finalize"] = {
        "status": "ready",
        "branch": slug,
        "sha": branch_head,
        "ready_at": now,
        "worker_session_id": ctx.actor_id.strip(),
    }

    return state


def _on_enter_finalize_handoff(state: dict[str, StateValue], ctx: TargetContext) -> dict[str, StateValue]:
    """Validate finalize.status == ready, write handed_off metadata."""
    finalize = _normalize_finalize_state(state.get("finalize"))
    if finalize.get("status") != "ready":
        raise ValueError(f"finalize state for {ctx.slug} is not ready")

    now = datetime.now(UTC).isoformat()
    state["finalize"] = {
        **finalize,  # type: ignore[dict-item]
        "status": "handed_off",
        "handoff_session_id": ctx.actor_id,
        "handed_off_at": now,
    }

    return state


# ── Ordered lifecycle state definitions ──────────────────────────────────────
LIFECYCLE_STATE_DEFS: list[State] = [
    # Prepare phases
    State("input_assessment"),
    State("triangulation"),
    State("requirements_review"),
    State("test_spec_build"),
    State("test_spec_review"),
    State("plan_drafting"),
    State("plan_review"),
    State("gate"),
    State("grounding_check"),
    State("re_grounding"),
    State("prepared", on_enter=_on_enter_prepared),
    # Work phases
    State("build_started", on_enter=_on_enter_build_started),
    State("build_complete"),
    State("review_pending"),
    State("review_changes_requested", on_enter=_on_enter_review_changes),
    State("review_approved", on_enter=_on_enter_review_approved),
    State("finalize_ready", on_enter=_on_enter_finalize_ready),
    State("finalize_handed_off", on_enter=_on_enter_finalize_handoff),
]

# Derived list of state names for ordering queries
LIFECYCLE_STATES: list[str] = [s.name for s in LIFECYCLE_STATE_DEFS]

# ── Canonical current → (build_status, review_status) mapping ─────────────────
# Single source of truth for deriving legacy build/review status pairs from the
# v2 current value. Used by work.py dispatch and roadmap.py display.
CURRENT_TO_BUILD_REVIEW: dict[str, tuple[str, str]] = {
    "prepared": ("pending", "pending"),
    "build_started": ("started", "pending"),
    "build_complete": ("complete", "pending"),
    "review_pending": ("complete", "pending"),
    "review_changes_requested": ("started", "changes_requested"),
    "review_approved": ("complete", "approved"),
    "finalize_ready": ("complete", "approved"),
    "finalize_handed_off": ("complete", "approved"),
}


def build_lifecycle_machine() -> StateMachine:
    """Return the canonical work lifecycle state machine."""
    return StateMachine(states=LIFECYCLE_STATE_DEFS)
