"""Render compiled timeline into markdown context for agent injection."""

from __future__ import annotations

import json
import time

from teleclaude.memory.context.compiler import TimelineEntry


def render_context(entries: list[TimelineEntry]) -> str:
    """Render timeline entries to markdown matching memory-management-api output format."""
    if not entries:
        return ""

    observations = [e for e in entries if e.kind == "observation" and e.observation]
    summaries = [e for e in entries if e.kind == "summary" and e.summary]

    parts: list[str] = ["# Memory Context\n"]

    if observations:
        parts.append(f"## Recent Observations (last {len(observations)})\n")
        parts.append("| # | Type | Title | When |")
        parts.append("|---|------|-------|------|")

        now_epoch = int(time.time())
        for i, entry in enumerate(observations, 1):
            obs = entry.observation
            assert obs is not None
            when = _relative_time(now_epoch, obs.created_at_epoch)
            title = (obs.title or "Untitled")[:60]
            parts.append(f"| {i} | {obs.type} | {title} | {when} |")

        parts.append("")

        for i, entry in enumerate(observations, 1):
            obs = entry.observation
            assert obs is not None
            title = obs.title or "Untitled"
            parts.append(f"### {i}. {title}")

            concepts_str = ""
            if obs.concepts:
                try:
                    concepts_list = json.loads(obs.concepts)
                    if concepts_list:
                        concepts_str = f" | **Concepts:** {', '.join(concepts_list)}"
                except (json.JSONDecodeError, TypeError):
                    pass

            parts.append(f"**Type:** {obs.type}{concepts_str}")

            if obs.narrative:
                parts.append(f"> {obs.narrative}\n")

            if obs.facts:
                try:
                    facts_list = json.loads(obs.facts)
                    if facts_list:
                        parts.append("**Facts:**")
                        for fact in facts_list:
                            parts.append(f"- {fact}")
                        parts.append("")
                except (json.JSONDecodeError, TypeError):
                    pass

            parts.append("---\n")

    if summaries:
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

    return "\n".join(parts).strip()


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
