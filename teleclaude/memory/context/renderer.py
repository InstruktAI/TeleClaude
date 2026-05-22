"""Render compiled timeline into markdown context for agent injection."""

from __future__ import annotations

import json
import time

from teleclaude.memory.context.compiler import TimelineEntry

MEMORY_INDEX_CAP = 100
MEMORY_EXPANDED_TOP_N = 10


def render_context(entries: list[TimelineEntry]) -> str:
    """Render timeline entries as markdown for agent context injection."""
    if not entries:
        return ""

    observations = [e for e in entries if e.kind == "observation" and e.observation]
    summaries = [e for e in entries if e.kind == "summary" and e.summary]

    parts: list[str] = ["# Memory Context\n"]

    if observations:
        _render_observations(observations, parts)

    if summaries:
        _render_summaries(summaries, parts)

    return "\n".join(parts).strip()


def _render_observations(observations: list[TimelineEntry], parts: list[str]) -> None:
    """Render index table (up to MEMORY_INDEX_CAP) and expanded detail (up to MEMORY_EXPANDED_TOP_N)."""
    total = len(observations)
    indexed = observations[:MEMORY_INDEX_CAP]

    if total <= MEMORY_INDEX_CAP:
        parts.append(f"## Index ({total} memories, newest first)\n")
    else:
        parts.append(f"## Index ({MEMORY_INDEX_CAP} of {total} memories, newest first)\n")

    parts.append("| # | Type | Title | When |")
    parts.append("|---|------|-------|------|")

    now_epoch = int(time.time())
    for i, entry in enumerate(indexed, 1):
        obs = entry.observation
        assert obs is not None
        when = _relative_time(now_epoch, obs.created_at_epoch)
        title = (obs.title or "Untitled")[:60]
        parts.append(f"| {i} | {obs.type} | {title} | {when} |")

    parts.append("")

    expanded = indexed[:MEMORY_EXPANDED_TOP_N]
    if len(expanded) >= MEMORY_EXPANDED_TOP_N:
        parts.append(f"## Top {MEMORY_EXPANDED_TOP_N} — Expanded\n")
    else:
        parts.append("## Expanded\n")

    for i, entry in enumerate(expanded, 1):
        obs = entry.observation
        assert obs is not None
        _render_observation_detail(i, obs, parts)


def _render_observation_detail(index: int, obs: object, parts: list[str]) -> None:
    """Render a single observation's detail block."""
    title = obs.title or "Untitled"  # type: ignore[attr-defined]
    parts.append(f"### {index}. {title}")

    concepts_str = _format_concepts(obs.concepts)  # type: ignore[attr-defined]
    parts.append(f"**Type:** {obs.type}{concepts_str}")  # type: ignore[attr-defined]

    if obs.narrative:  # type: ignore[attr-defined]
        parts.append(f"> {obs.narrative}\n")  # type: ignore[attr-defined]

    _render_facts(obs.facts, parts)  # type: ignore[attr-defined]
    parts.append("---\n")


def _format_concepts(concepts: str | None) -> str:
    """Format concepts JSON into display string."""
    if not concepts:
        return ""
    try:
        concepts_list = json.loads(concepts)
        if concepts_list:
            return f" | **Concepts:** {', '.join(concepts_list)}"
    except (json.JSONDecodeError, TypeError):
        pass
    return ""


def _render_facts(facts: str | None, parts: list[str]) -> None:
    """Render facts list if present."""
    if not facts:
        return
    try:
        facts_list = json.loads(facts)
        if facts_list:
            parts.append("**Facts:**")
            for fact in facts_list:
                parts.append(f"- {fact}")
            parts.append("")
    except (json.JSONDecodeError, TypeError):
        pass


def _render_summaries(summaries: list[TimelineEntry], parts: list[str]) -> None:
    """Render session summary blocks."""
    parts.append("## Session Summaries\n")
    for entry in summaries:
        summ = entry.summary
        assert summ is not None
        parts.append(f"### Session: {summ.project}")
        if summ.investigated:
            parts.append(f"- **Investigated:** {summ.investigated}")
        if summ.learned:
            parts.append(f"- **Learned:** {summ.learned}")
        if summ.completed:
            parts.append(f"- **Completed:** {summ.completed}")
        if summ.next_steps:
            parts.append(f"- **Next Steps:** {summ.next_steps}")
        parts.append("")


def _relative_time(now_epoch: int, then_epoch: int) -> str:
    """Format epoch difference as human-readable relative time."""
    diff = now_epoch - then_epoch
    if diff < 60:
        return "just now"
    if diff < 3600:
        mins = diff // 60
        return f"{mins}m ago"
    if diff < 86400:
        hours = diff // 3600
        return f"{hours}h ago"
    days = diff // 86400
    return f"{days}d ago"
