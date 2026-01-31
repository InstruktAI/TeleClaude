#!/usr/bin/env -S uv run --quiet

"""Search native agent session transcripts (~/.claude, ~/.codex, ~/.gemini)."""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from teleclaude.constants import AGENT_METADATA
from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import collect_transcript_messages


def _discover_transcripts(agent: AgentName) -> list[tuple[Path, float]]:
    """Find all transcript files for an agent, return (path, mtime) sorted newest first."""
    meta = AGENT_METADATA[agent.value]
    session_dir = Path(str(meta["session_dir"])).expanduser()

    # Claude stores transcripts in ~/.claude/projects/*/*.jsonl, not sessions/
    if agent == AgentName.CLAUDE:
        projects_dir = session_dir.parent / "projects"
        if projects_dir.exists():
            session_dir = projects_dir

    if not session_dir.exists():
        return []

    pattern = str(meta["log_pattern"])
    # rglob already recurses, strip leading **/ if present
    if pattern.startswith("**/"):
        pattern = pattern[3:]
    files: list[tuple[Path, float]] = []
    for p in session_dir.rglob(pattern):
        if p.is_file():
            files.append((p, p.stat().st_mtime))

    files.sort(key=lambda x: x[1], reverse=True)
    return files


def _extract_project_from_path(path: Path, agent: AgentName) -> str:
    """Extract project name from native transcript path."""
    if agent == AgentName.CLAUDE:
        # ~/.claude/projects/-Users-Morriz-Workspace-Foo/session.jsonl
        # Parent dir name is the mangled project path
        mangled = path.parent.name
        # Take last segment of the original path
        parts = mangled.split("-")
        # Find meaningful suffix (skip empty parts from leading dash)
        non_empty = [p for p in parts if p]
        if non_empty:
            return non_empty[-1]
    elif agent == AgentName.GEMINI:
        # ~/.gemini/tmp/<hash>/chats/session-*.json — hash isn't useful
        return "gemini"
    elif agent == AgentName.CODEX:
        # ~/.codex/.history/sessions/YYYY/MM/DD/rollout-*.jsonl
        return "codex"
    return "unknown"


def _extract_session_id(path: Path, agent: AgentName) -> str:
    """Extract session ID from transcript filename."""
    stem = path.stem
    if agent == AgentName.CLAUDE:
        # UUID.jsonl or agent-<hash>.jsonl
        return stem[:12]
    if agent == AgentName.GEMINI:
        # session-2026-01-26T12-27-b6df3607.json
        return stem.replace("session-", "")[:12]
    if agent == AgentName.CODEX:
        # rollout-2025-12-05T23-52-23-<uuid>_<timestamp>.jsonl
        return stem[:12]
    return stem[:12]


def _match_context(text: str, term: str, window: int = 80) -> Optional[str]:
    """Return a context snippet with term in the middle, or None."""
    lower = text.lower()
    term_lower = term.lower()
    idx = lower.find(term_lower)
    if idx == -1:
        return None
    start = max(0, idx - window)
    end = min(len(text), idx + len(term) + window)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def truncate_display(text: str, max_len: int = 70) -> str:
    """Truncate text to max length."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def format_timestamp(mtime: float) -> str:
    """Format mtime to human readable."""
    dt = datetime.fromtimestamp(mtime)
    return dt.strftime("%b %d, %Y %H:%M")


def display_history(agent_name: AgentName, search_term: str = "", limit: int = 20) -> None:
    """Display session history by scanning native agent transcript dirs."""
    transcripts = _discover_transcripts(agent_name)

    if not transcripts:
        print(f"No transcripts found for {agent_name.value}")
        return

    results: list[dict[str, str]] = []
    scanned = 0

    for path, mtime in transcripts:
        if len(results) >= limit:
            break
        # Limit scanning to avoid being too slow on 1600+ files
        scanned += 1
        if scanned > 200:
            break

        messages = collect_transcript_messages(str(path), agent_name)
        if not messages:
            continue

        transcript_text = "\n\n".join(text for _, text in messages)

        snippet = _match_context(transcript_text, search_term)
        if not snippet:
            continue
        topic = truncate_display(snippet, 70)

        results.append(
            {
                "timestamp": format_timestamp(mtime),
                "project": _extract_project_from_path(path, agent_name),
                "topic": topic,
                "session_id": _extract_session_id(path, agent_name),
                "path": str(path),
            }
        )

    if not results:
        print(f"No conversations found matching '{search_term}'")
        return

    print(f"\nSearch results for '{search_term}' ({len(results)} found):\n")

    # Header
    print(f"{'#':>4} | {'Date/Time':<17} | {'Project':<20} | {'Topic':<70} | {'Session':<12}")
    print("-" * 130)

    for i, entry in enumerate(results, 1):
        print(
            f"{i:>4} | {entry['timestamp']:<17} | {entry['project']:<20} | {entry['topic']:<70} | {entry['session_id']:<12}"
        )

    print("\n" + "-" * 80)
    resume_tpl = str(AGENT_METADATA[agent_name.value].get("resume_template", ""))
    if resume_tpl:
        example = resume_tpl.format(base_cmd=agent_name.value, session_id="<session-id>")
        print(f"Resume: {example}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Search native agent session transcripts.")
    parser.add_argument("--agent", required=True, help="Agent name (claude|codex|gemini).")
    parser.add_argument("terms", nargs=argparse.REMAINDER, help="Search terms.")
    args = parser.parse_args()

    agent_str = args.agent.strip()
    try:
        agent_name = AgentName.from_str(agent_str)
    except ValueError:
        print(f"Unknown agent: {agent_str}")
        sys.exit(1)

    search_term = " ".join(args.terms).strip()
    if not search_term:
        print("Search terms are required. Example: history.py --agent claude <terms>")
        sys.exit(1)
    display_history(agent_name, search_term)


if __name__ == "__main__":
    main()
