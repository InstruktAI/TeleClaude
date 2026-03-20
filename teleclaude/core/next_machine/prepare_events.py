"""Prepare state machine — lifecycle events and artifact checks.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import (
    PreparePhase,
    default_state,
)
from teleclaude.core.next_machine.roadmap import load_roadmap_slugs
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
                source=f"orchestrator/{(get_session_id() or 'unknown')}",
                level=EventLevel.WORKFLOW,
                domain="software-development",
                description=description,
                entity=slug,
                payload=dict(payload),
            )
        except Exception:  # pylint: disable=broad-exception-caught
            pass  # Never block prepare on event emission failure

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_emit())
    except RuntimeError:
        # No running loop (thread or sync CLI context) — fire-and-forget via new event loop
        try:
            asyncio.run(_emit())
        except Exception:  # pylint: disable=broad-exception-caught
            pass  # Never block prepare on event emission failure


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
                **default_state()["grounding"],  # type: ignore
                **grounding,  # type: ignore[dict-item]
            }
            grounding_dict["valid"] = False
            grounding_dict["invalidated_at"] = now
            grounding_dict["invalidation_reason"] = "files_changed"
            state["grounding"] = grounding_dict  # type: ignore[assignment]
            state["current"] = PreparePhase.GROUNDING_CHECK.value
            write_phase_state(cwd, slug, state)
            _emit_prepare_event(
                "domain.software-development.prepare.grounding_invalidated",
                {"slug": slug, "reason": "files_changed", "changed_paths": overlap},  # type: ignore[dict-item]
            )
            invalidated.append(slug)

    return {"invalidated": invalidated}


__all__ = [
    "_emit_prepare_event",
    "_has_test_spec_artifacts",
    "invalidate_stale_preparations",
]
