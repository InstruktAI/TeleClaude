"""Prepare state machine — lifecycle events and phase derivation.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import (
    DEFAULT_STATE,
    DOR_READY_THRESHOLD,
    PreparePhase,
    StateValue,
)
from teleclaude.core.next_machine.build_gates import check_file_has_content
from teleclaude.core.next_machine.roadmap import load_roadmap_slugs
from teleclaude.core.next_machine.slug_resolution import check_file_exists
from teleclaude.core.next_machine.state_io import read_phase_state, write_phase_state
from teleclaude.events.envelope import EventLevel
from teleclaude.events.producer import emit_event
from teleclaude.session_identity import get_session_id


def _emit_prepare_event(event_type: str, payload: dict[str, str | list[str]]) -> None:
    """Fire-and-forget lifecycle event emission for prepare state machine."""

    async def _emit() -> None:
        try:
            slug = str(payload.get("slug", ""))
            description = f"prepare.{event_type.split('.')[-1]}: {slug}"
            await emit_event(
                event=event_type,
                source=f"orchestrator/{get_session_id() or 'unknown'}",
                level=EventLevel.WORKFLOW,
                domain="software-development",
                description=description,
                entity=slug,
                payload=dict(payload),  # type: ignore[arg-type]
            )
        except (OSError, RuntimeError, ValueError):
            pass  # Never block prepare on event emission failure

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_emit())
    except RuntimeError:
        # No running loop (thread or sync CLI context) — fire-and-forget via new event loop
        try:
            asyncio.run(_emit())
        except RuntimeError:
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


def _review_needs_work(state: dict[str, StateValue], key: str) -> bool:
    """Return whether a review verdict still blocks progression."""
    review = state.get(key, {})
    verdict = (isinstance(review, dict) and review.get("verdict")) or ""
    return not verdict or verdict in ("needs_work", "needs_decision")


def _spec_review_needs_work(state: dict[str, StateValue]) -> bool:
    """Return whether test spec review is still awaiting approval."""
    review = state.get("test_spec_review", {})
    verdict = (isinstance(review, dict) and review.get("verdict")) or ""
    return not verdict or verdict == "needs_work"


def _has_lifecycle_artifact(
    cwd: str,
    slug: str,
    state: dict[str, StateValue],
    artifact_path: str,
    artifact_key: str,
) -> bool:
    """Check artifact existence with v2 lifecycle gating."""
    has_artifact = check_file_has_content(cwd, f"todos/{slug}/{artifact_path}")
    return has_artifact and _is_artifact_produced_v2(state, artifact_key)


def _has_prepared_test_specs(cwd: str, slug: str, state: dict[str, StateValue]) -> bool:
    """Check whether test spec artifacts exist and have lifecycle stamps."""
    has_test_specs = _has_test_spec_artifacts(cwd, slug)
    return has_test_specs and _is_artifact_produced_v2(state, "test_specs")


def _is_dor_ready(state: dict[str, StateValue]) -> bool:
    """Return whether the DOR gate score meets the ready threshold."""
    dor = state.get("dor", {})
    dor_score = dor.get("score") if isinstance(dor, dict) else None
    return isinstance(dor_score, int) and dor_score >= DOR_READY_THRESHOLD


def _derive_prepare_phase(slug: str, cwd: str, state: dict[str, StateValue]) -> PreparePhase:
    """Derive the initial prepare phase from artifact existence when no durable phase is set.

    For v2 state, ghost artifact protection (R5) means a file on disk without a
    corresponding produced_at lifecycle record is treated as not produced.
    For v1 state, file existence is the sole signal (backward compat).
    """
    has_input = check_file_exists(cwd, f"todos/{slug}/input.md")
    phase = PreparePhase.INPUT_ASSESSMENT if has_input else PreparePhase.TRIANGULATION
    if _has_lifecycle_artifact(cwd, slug, state, "requirements.md", "requirements"):
        phase = PreparePhase.TEST_SPEC_BUILD
        if _review_needs_work(state, "requirements_review"):
            phase = PreparePhase.REQUIREMENTS_REVIEW
        elif _has_prepared_test_specs(cwd, slug, state):
            phase = PreparePhase.PLAN_DRAFTING
            if _spec_review_needs_work(state):
                phase = PreparePhase.TEST_SPEC_REVIEW
            elif _has_lifecycle_artifact(
                cwd,
                slug,
                state,
                "implementation-plan.md",
                "implementation_plan",
            ):
                phase = PreparePhase.GATE
                if _review_needs_work(state, "plan_review"):
                    phase = PreparePhase.PLAN_REVIEW
                elif _is_dor_ready(state):
                    phase = PreparePhase.GROUNDING_CHECK
    return phase


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
