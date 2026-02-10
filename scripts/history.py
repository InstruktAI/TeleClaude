#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "instruktai-python-logger",
#     "python-dotenv",
#     "pydantic",
#     "pyyaml",
#     "aiohttp",
#     "dateparser",
#     "munch",
# ]
# ///

"""Search native agent session transcripts (~/.claude, ~/.codex, ~/.gemini)."""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from teleclaude.constants import AGENT_PROTOCOL
from teleclaude.core.agents import AgentName
from teleclaude.core.dates import format_local_datetime
from teleclaude.utils.transcript import collect_transcript_messages, parse_session_transcript


def _discover_transcripts(agent: AgentName) -> list[tuple[Path, float]]:
    """Find all transcript files for an agent, return (path, mtime) sorted newest first."""
    meta = AGENT_PROTOCOL[agent.value]
    session_dirs: list[Path] = [Path(str(meta["session_dir"])).expanduser()]

    # Claude stores transcripts in ~/.claude/projects/*/*.jsonl, not sessions/
    if agent == AgentName.CLAUDE:
        projects_dir = session_dirs[0].parent / "projects"
        if projects_dir.exists():
            session_dirs = [projects_dir]

    if agent == AgentName.CODEX:
        # Codex stores active sessions in ~/.codex/sessions and history in ~/.codex/.history/sessions.
        session_dirs.append(Path("~/.codex/.history/sessions").expanduser())

    pattern = str(meta["log_pattern"])
    # rglob already recurses, strip leading **/ if present
    if pattern.startswith("**/"):
        pattern = pattern[3:]
    files: list[tuple[Path, float]] = []
    seen: set[Path] = set()
    for session_dir in session_dirs:
        if not session_dir.exists():
            continue
        for p in session_dir.rglob(pattern):
            if p.is_file() and p not in seen:
                files.append((p, p.stat().st_mtime))
                seen.add(p)

    if not files:
        return []

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
        # or rollout-2026-02-02T03-01-53-<uuid>.jsonl
        return stem.split("_", 1)[0]
    return stem[:12]


def _match_context(text: str, term: str, window: int = 80) -> Optional[str]:
    """Return a context snippet if ALL words in term appear in text (AND logic).

    Shows context around the rarest (last-found) word for most relevant snippet.
    """
    lower = text.lower()
    words = term.lower().split()
    if not words:
        return None

    # All words must be present
    best_idx = -1
    best_word = words[0]
    for word in words:
        idx = lower.find(word)
        if idx == -1:
            return None  # AND: all words must match
        # Use last word's position (often most specific)
        best_idx = idx
        best_word = word

    start = max(0, best_idx - window)
    end = min(len(text), best_idx + len(best_word) + window)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def truncate_display(text: str, max_len: int = 70) -> str:
    """Truncate text to max length."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def format_timestamp(mtime: float) -> str:
    """Format mtime to human readable in local timezone."""
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return format_local_datetime(dt, include_date=True)


def _scan_one(path: Path, mtime: float, agent_name: AgentName, search_term: str) -> Optional[dict[str, str]]:
    """Scan a single transcript file. Returns a result dict or None."""
    messages = collect_transcript_messages(str(path), agent_name)
    if not messages:
        return None
    transcript_text = "\n\n".join(text for _, text in messages)
    snippet = _match_context(transcript_text, search_term)
    if not snippet:
        return None
    return {
        "timestamp": format_timestamp(mtime),
        "agent": agent_name.value,
        "project": _extract_project_from_path(path, agent_name),
        "topic": truncate_display(snippet, 70),
        "session_id": _extract_session_id(path, agent_name),
        "path": str(path),
        "_mtime": str(mtime),
    }


def scan_agent_history(agent_name: AgentName, search_term: str) -> List[dict[str, str]]:
    """Scan history for a single agent."""
    transcripts = _discover_transcripts(agent_name)
    if not transcripts:
        return []

    # Cap files to scan but use threads to scan them in parallel
    to_scan = transcripts[:500]
    results: list[dict[str, str]] = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_scan_one, path, mtime, agent_name, search_term): mtime for path, mtime in to_scan}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    return results


def find_transcript(agents: List[AgentName], session_id: str) -> Optional[Tuple[Path, AgentName]]:
    """Find a transcript file by session ID prefix across agents."""
    needle = session_id.lower()
    for agent in agents:
        for path, _ in _discover_transcripts(agent):
            extracted = _extract_session_id(path, agent).lower()
            # Match against extracted ID or the raw stem for fuller matches
            if extracted.startswith(needle) or path.stem.lower().startswith(needle):
                return path, agent
            # Also match partial UUID anywhere in stem (e.g. "f3625680")
            if needle in path.stem.lower():
                return path, agent
    return None


def show_transcript(
    agents: List[AgentName],
    session_id: str,
    tail_chars: int = 0,
    include_thinking: bool = False,
) -> None:
    """Find and render a session transcript using the existing parser."""
    match = find_transcript(agents, session_id)
    if not match:
        print(f"No transcript found for session '{session_id}'")
        sys.exit(1)

    path, agent = match
    rendered = parse_session_transcript(
        str(path),
        f"{agent.value} session — {path.stem}",
        agent_name=agent,
        tail_chars=tail_chars,
        include_thinking=include_thinking,
        include_tools=False,
    )
    print(rendered)


def display_combined_history(agents: List[AgentName], search_term: str = "", limit: int = 20) -> None:
    """Display session history for multiple agents."""
    all_results: List[dict[str, str]] = []

    # Sequential agent scanning is fine — file scanning within agents is already parallel.
    for agent in agents:
        results = scan_agent_history(agent, search_term)
        all_results.extend(results)
        # We don't track exact scan count per agent here easily without refactor,
        # but results count is what matters most.

    if not all_results:
        print(f"No conversations found matching '{search_term}' across {', '.join(a.value for a in agents)}")
        return

    # Sort by mtime descending (newest first) and cap
    all_results.sort(key=lambda r: float(r["_mtime"]), reverse=True)
    all_results = all_results[:limit]

    print(f"\nSearch results for '{search_term}' ({len(all_results)} found):\n")

    # Header with Agent column
    print(f"{'#':>4} | {'Date/Time':<17} | {'Agent':<8} | {'Project':<20} | {'Topic':<70} | {'Session':<12}")
    print("-" * 140)

    for i, entry in enumerate(all_results, 1):
        print(
            f"{i:>4} | {entry['timestamp']:<17} | {entry['agent']:<8} | {entry['project']:<20} | {entry['topic']:<70} | {entry['session_id']:<12}"
        )

    print("\n" + "-" * 80)
    # Resume hints
    shown_agents = {entry["agent"] for entry in all_results}
    for agent_str in sorted(shown_agents):
        meta = AGENT_PROTOCOL.get(agent_str)
        if meta:
            resume_tpl = str(meta.get("resume_template", ""))
            if resume_tpl:
                example = resume_tpl.format(base_cmd=agent_str, session_id="<session-id>")
                print(f"Resume {agent_str}: {example}")


def _parse_agents(agent_arg: str) -> List[AgentName]:
    """Parse agent argument into list of AgentName."""
    agent_arg = agent_arg.strip().lower()
    if agent_arg == "all":
        return [AgentName.CLAUDE, AgentName.CODEX, AgentName.GEMINI]

    agents: List[AgentName] = []
    for p in agent_arg.split(","):
        p = p.strip()
        if not p:
            continue
        try:
            agents.append(AgentName.from_str(p))
        except ValueError:
            print(f"Unknown agent: {p}")
            sys.exit(1)
    return agents


def main() -> None:
    parser = argparse.ArgumentParser(description="Search native agent session transcripts.")
    parser.add_argument("--agent", required=True, help="Agent name(s) (claude,codex,gemini) or 'all'.")
    parser.add_argument("--show", metavar="SESSION_ID", help="Show full parsed transcript for a session.")
    parser.add_argument("--thinking", action="store_true", help="Include thinking blocks in --show output.")
    parser.add_argument(
        "--tail", type=int, default=0, help="Limit output to last N chars (0=unlimited, default for --show)."
    )
    parser.add_argument("terms", nargs=argparse.REMAINDER, help="Search terms.")
    args = parser.parse_args()

    selected_agents = _parse_agents(args.agent)

    if args.show:
        show_transcript(selected_agents, args.show, tail_chars=args.tail, include_thinking=args.thinking)
        return

    search_term = " ".join(args.terms).strip()
    if not search_term:
        print("Search terms are required. Example: history.py --agent all <terms>")
        sys.exit(1)

    display_combined_history(selected_agents, search_term)


if __name__ == "__main__":
    main()
