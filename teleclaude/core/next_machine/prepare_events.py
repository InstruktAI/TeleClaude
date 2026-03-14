"""Prepare state machine — lifecycle events and phase derivation.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import (
    DEFAULT_STATE,
    DOR_READY_THRESHOLD,
    PreparePhase,
    StateValue,
)
from teleclaude.core.next_machine.roadmap import load_roadmap_slugs
from teleclaude.core.next_machine.state_io import read_phase_state, write_phase_state


def _emit_prepare_event(event_type: str, payload: dict[str, str | list[str]]) -> None:
    """Fire-and-forget lifecycle event emission for prepare state machine."""
    from teleclaude.events.envelope import EventLevel
    from teleclaude.events.producer import emit_event

    async def _emit() -> None:
        try:
            slug = str(payload.get("slug", ""))
            description = f"prepare.{event_type.split('.')[-1]}: {slug}"
            await emit_event(
                event=event_type,
                source=f"orchestrator/{os.environ.get('TELECLAUDE_SESSION_ID', 'unknown')}",
                level=EventLevel.WORKFLOW,
                domain="software-development",
                description=description,
                entity=slug,
                payload=dict(payload),  # type: ignore[arg-type]
            )
        except Exception:
            pass  # Never block prepare on event emission failure

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_emit())
    except RuntimeError:
        # No running loop (thread or sync CLI context) — fire-and-forget via new event loop
        try:
            asyncio.run(_emit())
        except Exception:
            pass  # Never block prepare on event emission failure


def _is_artifact_produced_v2(state: dict[str, StateValue], artifact_key: str) -> bool:
    """Check whether a v2 lifecycle record confirms the artifact was properly produced.

    For v1 state (no schema_version), always returns True so file-existence is
    the sole signal (backward compatibility).
    """
    schema_version = state.get("schema_version")
    if not isinstance(schema_version, int) or schema_version < 2:
        return True  # v1: file-existence wins
    artifacts = state.get("artifacts", {})
    if not isinstance(artifacts, dict):
        return False
    entry = artifacts.get(artifact_key, {})
    if not isinstance(entry, dict):
        return False
    produced_at = entry.get("produced_at", "")
    return isinstance(produced_at, str) and bool(produced_at)


def _has_test_spec_artifacts(cwd: str, slug: str) -> bool:
    """Check if xfail-marked test spec files exist in the worktree."""
    worktree_path = Path(cwd) / WORKTREE_DIR / slug
    if not worktree_path.is_dir():
        return False
    # Look for test files containing xfail markers
    for test_file in worktree_path.rglob("test_*.py"):
        try:
            content = test_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if "xfail" in content:
            return True
    return False


def _derive_prepare_phase(slug: str, cwd: str, state: dict[str, StateValue]) -> PreparePhase:
    """Derive the initial prepare phase from artifact existence when no durable phase is set.

    For v2 state, ghost artifact protection (R5) means a file on disk without a
    corresponding produced_at lifecycle record is treated as not produced.
    For v1 state, file existence is the sole signal (backward compat).
    """
    from teleclaude.core.next_machine.build_gates import check_file_has_content
    from teleclaude.core.next_machine.slug_resolution import check_file_exists

    has_input = check_file_exists(cwd, f"todos/{slug}/input.md")
    has_requirements = check_file_has_content(cwd, f"todos/{slug}/requirements.md")

    # Ghost artifact protection (R5)
    if has_requirements and not _is_artifact_produced_v2(state, "requirements"):
        has_requirements = False

    if has_input and not has_requirements:
        return PreparePhase.INPUT_ASSESSMENT
    if not has_requirements:
        return PreparePhase.TRIANGULATION

    req_review = state.get("requirements_review", {})
    req_verdict = (isinstance(req_review, dict) and req_review.get("verdict")) or ""
    if not req_verdict or req_verdict in ("needs_work", "needs_decision"):
        return PreparePhase.REQUIREMENTS_REVIEW

    # After requirements approved: check test spec phase
    has_test_specs = _has_test_spec_artifacts(cwd, slug)
    if not has_test_specs:
        return PreparePhase.TEST_SPEC_BUILD

    spec_review = state.get("test_spec_review", {})
    spec_verdict = (isinstance(spec_review, dict) and spec_review.get("verdict")) or ""
    if not spec_verdict or spec_verdict in ("needs_work",):
        return PreparePhase.TEST_SPEC_REVIEW

    has_plan = check_file_has_content(cwd, f"todos/{slug}/implementation-plan.md")
    # Ghost artifact protection for plan
    if has_plan and not _is_artifact_produced_v2(state, "implementation_plan"):
        has_plan = False

    if not has_plan:
        return PreparePhase.PLAN_DRAFTING

    plan_review = state.get("plan_review", {})
    plan_verdict = (isinstance(plan_review, dict) and plan_review.get("verdict")) or ""
    if not plan_verdict or plan_verdict in ("needs_work", "needs_decision"):
        return PreparePhase.PLAN_REVIEW

    dor = state.get("dor", {})
    dor_score = dor.get("score") if isinstance(dor, dict) else None
    if not (isinstance(dor_score, int) and dor_score >= DOR_READY_THRESHOLD):
        return PreparePhase.GATE

    return PreparePhase.GROUNDING_CHECK


def invalidate_stale_preparations(cwd: str, changed_paths: list[str]) -> dict[str, list[str]]:
    """Scan all active todos and invalidate those with overlapping referenced paths.

    Designed for post-commit hooks or CI to invalidate stale preparations.
    Returns {"invalidated": ["slug-a", ...]} for each invalidated slug.
    """
    invalidated: list[str] = []
    now = datetime.now(UTC).isoformat()
    changed_set = set(changed_paths)

    for slug in load_roadmap_slugs(cwd):
        state = read_phase_state(cwd, slug)
        grounding = state.get("grounding", {})
        if not isinstance(grounding, dict):
            continue
        referenced = grounding.get("referenced_paths", [])
        if not isinstance(referenced, list):
            continue
        overlap = [p for p in referenced if p in changed_set]
        if overlap:
            grounding_dict: dict[str, bool | str | list[str] | int] = {  # type: ignore[unused-ignore]
                **DEFAULT_STATE["grounding"],  # type: ignore
                **grounding,  # type: ignore[dict-item]
            }
            grounding_dict["valid"] = False
            grounding_dict["invalidated_at"] = now
            grounding_dict["invalidation_reason"] = "files_changed"
            state["grounding"] = grounding_dict  # type: ignore[assignment]
            state["prepare_phase"] = PreparePhase.GROUNDING_CHECK.value
            write_phase_state(cwd, slug, state)
            _emit_prepare_event(
                "domain.software-development.prepare.grounding_invalidated",
                {"slug": slug, "reason": "files_changed", "changed_paths": overlap},  # type: ignore[dict-item]
            )
            invalidated.append(slug)

    return {"invalidated": invalidated}


__all__ = [
    "_derive_prepare_phase",
    "_emit_prepare_event",
    "_has_test_spec_artifacts",
    "invalidate_stale_preparations",
]
