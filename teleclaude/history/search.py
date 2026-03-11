"""Reusable history search functions backed by conversation mirrors."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Awaitable, Sequence, TypedDict

import httpx

from teleclaude.constants import AGENT_PROTOCOL, API_SOCKET_PATH
from teleclaude.core.agents import AgentName
from teleclaude.mirrors.store import MirrorRecord, MirrorSearchResult, get_mirror, search_mirrors
from teleclaude.utils.transcript import parse_session_transcript
from teleclaude.utils.transcript_discovery import discover_transcripts, extract_session_id

API_TCP_PORT = int(os.getenv("API_TCP_PORT", "8420"))
BASE_URL = "http://localhost"


class RemoteComputerPayload(TypedDict, total=False):
    name: str
    host: str | None
    is_local: bool
    status: str


class RemoteMirrorRow(TypedDict, total=False):
    session_id: str
    computer: str
    agent: str
    project: str
    title: str
    sort_timestamp: str
    timestamp: str
    topic: str


class RemoteSearchPayload(TypedDict):
    computer: str
    rows: list[RemoteMirrorRow]


def _coerce_remote_computers(payload: object) -> list[RemoteComputerPayload]:
    if not isinstance(payload, list):
        return []
    computers: list[RemoteComputerPayload] = []
    for item in payload:
        if isinstance(item, dict):
            computers.append(item)
    return computers


def _coerce_remote_rows(payload: object) -> list[RemoteMirrorRow]:
    if not isinstance(payload, list):
        return []
    rows: list[RemoteMirrorRow] = []
    for item in payload:
        if isinstance(item, dict):
            rows.append(item)
    return rows


def find_transcript(agents: Sequence[AgentName], session_id: str) -> tuple[Path, AgentName] | None:
    """Find a transcript file by session ID prefix across agents."""
    needle = session_id.lower()
    for candidate in discover_transcripts(agents):
        extracted = extract_session_id(candidate.path, candidate.agent).lower()
        if extracted.startswith(needle) or candidate.path.stem.lower().startswith(needle):
            return candidate.path, candidate.agent
        if needle in candidate.path.stem.lower():
            return candidate.path, candidate.agent
    return None


def _tail_text(text: str, tail_chars: int) -> str:
    if tail_chars <= 0 or len(text) <= tail_chars:
        return text
    return text[-tail_chars:]


def _print_results(search_term: str, results: list[dict[str, str]], *, show_computer: bool, limit: int) -> None:
    if not results:
        return
    results = results[:limit]
    print(f"\nSearch results for '{search_term}' ({len(results)} found):\n")

    for index, entry in enumerate(results, start=1):
        parts = [f"{index:>4}", entry["timestamp"]]
        if show_computer:
            parts.append(entry["computer"])
        parts += [entry["agent"], entry["project"], entry["topic"], entry["session_id"]]
        print(" | ".join(parts))

    print()
    shown_agents = {entry["agent"] for entry in results}
    for agent_str in sorted(shown_agents):
        meta = AGENT_PROTOCOL.get(agent_str)
        if meta:
            resume_tpl = str(meta.get("resume_template", ""))
            if resume_tpl:
                example = resume_tpl.format(base_cmd=agent_str, session_id="<session-id>")
                print(f"Resume {agent_str}: {example}")


def _local_result_to_entry(result: MirrorSearchResult) -> dict[str, str]:
    return {
        "_sort": result.sort_timestamp,
        "timestamp": result.timestamp,
        "computer": result.computer,
        "agent": result.agent,
        "project": result.project,
        "topic": result.topic,
        "session_id": result.session_id,
    }


def _mirror_to_display(mirror: MirrorRecord, *, tail_chars: int) -> str:
    header_lines = [mirror.title] if mirror.title else []
    if mirror.project:
        header_lines.append(f"Project: {mirror.project}")
    if mirror.computer:
        header_lines.append(f"Computer: {mirror.computer}")
    if mirror.timestamp_start:
        header_lines.append(f"Started: {mirror.timestamp_start}")
    header = "\n".join(header_lines)
    body = _tail_text(mirror.conversation_text, tail_chars)
    return f"{header}\n\n{body}".strip()


def _fetch_local_daemon_computers() -> list[RemoteComputerPayload]:
    transport = httpx.HTTPTransport(uds=API_SOCKET_PATH)
    with httpx.Client(transport=transport, base_url=BASE_URL, timeout=5.0) as client:
        response = client.get("/computers")
        response.raise_for_status()
        return _coerce_remote_computers(response.json())


def _resolve_remote_computer_urls(computers: Sequence[str]) -> tuple[dict[str, str], dict[str, str]]:
    try:
        discovered = _fetch_local_daemon_computers()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        error = f"Failed to resolve remote computers via local daemon: {exc}"
        return {}, {computer: error for computer in computers}

    resolved: dict[str, str] = {}
    errors: dict[str, str] = {}
    by_name = {str(item.get("name")): item for item in discovered}
    for computer in computers:
        item = by_name.get(computer)
        if item is None:
            errors[computer] = f"Computer '{computer}' not found in local daemon cache"
            continue
        host = item.get("host") or computer
        resolved[computer] = f"http://{host}:{API_TCP_PORT}"
    return resolved, errors


async def _remote_search(
    base_url: str, computer: str, search_term: str, agents: Sequence[AgentName], limit: int
) -> RemoteSearchPayload:
    params = {
        "q": search_term,
        "agent": ",".join(agent.value for agent in agents) if agents else "all",
        "limit": limit,
    }
    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        response = await client.get("/api/mirrors/search", params=params)
        response.raise_for_status()
        return {"computer": computer, "rows": _coerce_remote_rows(response.json())}


async def _remote_get(base_url: str, path: str) -> httpx.Response:
    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        response = await client.get(path)
        response.raise_for_status()
        return response


async def _run_remote_searches(
    tasks: Sequence[Awaitable[RemoteSearchPayload]],
) -> list[RemoteSearchPayload | BaseException]:
    return await asyncio.gather(*tasks, return_exceptions=True)


def display_combined_history(
    agents: list[AgentName],
    search_term: str = "",
    limit: int = 20,
    computers: Sequence[str] | None = None,
) -> None:
    """Display session history using local mirrors or remote daemon search."""
    if computers:
        resolved, errors = _resolve_remote_computer_urls(computers)
        tasks = [
            _remote_search(base_url, computer, search_term, agents, limit) for computer, base_url in resolved.items()
        ]
        results: list[dict[str, str]] = []
        if tasks:
            responses = asyncio.run(_run_remote_searches(tasks))
            for response, computer in zip(responses, resolved, strict=False):
                if isinstance(response, BaseException):
                    print(f"[{computer}] Remote search failed: {response}")
                    continue
                for row in response["rows"]:
                    results.append(
                        {
                            "_sort": str(row.get("sort_timestamp", "")),
                            "timestamp": str(row.get("timestamp", "")),
                            "computer": response["computer"],
                            "agent": str(row.get("agent", "")),
                            "project": str(row.get("project", "")),
                            "topic": str(row.get("topic", row.get("title", ""))),
                            "session_id": str(row.get("session_id", "")),
                        }
                    )
        for computer, message in errors.items():
            print(f"[{computer}] {message}")
        if not results:
            print(f"No conversations found matching '{search_term}' across {', '.join(computers)}")
            return
        results.sort(key=lambda entry: entry.get("_sort", ""), reverse=True)
        _print_results(search_term, results, show_computer=True, limit=limit)
        return

    local_results = [_local_result_to_entry(result) for result in search_mirrors(search_term, agents, limit=limit)]
    if not local_results:
        print(f"No conversations found matching '{search_term}' across {', '.join(agent.value for agent in agents)}")
        return
    _print_results(search_term, local_results, show_computer=False, limit=limit)


def show_transcript(
    agents: list[AgentName],
    session_id: str,
    tail_chars: int = 0,
    include_thinking: bool = False,
    raw: bool = False,
    computers: Sequence[str] | None = None,
) -> None:
    """Show a mirror or raw transcript for a local or remote session."""
    if computers:
        if len(computers) != 1:
            print("history show accepts exactly one --computer value")
            sys.exit(1)
        resolved, errors = _resolve_remote_computer_urls(computers)
        if errors:
            for message in errors.values():
                print(message)
            sys.exit(1)
        computer = computers[0]
        base_url = resolved[computer]
        path = f"/api/mirrors/{session_id}/transcript" if raw else f"/api/mirrors/{session_id}"
        try:
            response = asyncio.run(_remote_get(base_url, path))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"Failed to fetch session '{session_id}' from {computer}: {exc}")
            sys.exit(1)
        if raw:
            print(_tail_text(response.text, tail_chars))
            return
        payload = response.json()
        if not isinstance(payload, dict):
            print(f"Invalid mirror response for session '{session_id}'")
            sys.exit(1)
        mirror = MirrorRecord(
            session_id=str(payload.get("session_id", session_id)),
            computer=str(payload.get("computer", computer)),
            agent=str(payload.get("agent", "")),
            project=str(payload.get("project", "")),
            title=str(payload.get("title", "")),
            timestamp_start=payload.get("timestamp_start"),
            timestamp_end=payload.get("timestamp_end"),
            conversation_text=str(payload.get("conversation_text", "")),
            message_count=int(payload.get("message_count", 0) or 0),
            metadata={},
            created_at="",
            updated_at="",
        )
        print(_mirror_to_display(mirror, tail_chars=tail_chars))
        return

    mirror = get_mirror(session_id)
    if mirror and not raw:
        print(_mirror_to_display(mirror, tail_chars=tail_chars))
        return
    if mirror and raw:
        transcript_path = mirror.metadata.get("transcript_path")
        if isinstance(transcript_path, str) and transcript_path:
            path = Path(transcript_path).expanduser()
            if path.exists():
                print(_tail_text(path.read_text(encoding="utf-8"), tail_chars))
                return

    match = find_transcript(agents, session_id)
    if not match:
        print(f"No transcript found for session '{session_id}'")
        sys.exit(1)

    path, agent = match
    rendered = parse_session_transcript(
        str(path),
        f"{agent.value} session - {path.stem}",
        agent_name=agent,
        tail_chars=tail_chars,
        include_thinking=include_thinking,
        include_tools=False,
    )
    print(rendered)


def parse_agents(agent_arg: str) -> list[AgentName]:
    """Parse agent argument into list of AgentName."""
    agent_arg = agent_arg.strip().lower()
    if agent_arg == "all":
        return [AgentName.CLAUDE, AgentName.CODEX, AgentName.GEMINI]

    agents: list[AgentName] = []
    for part in agent_arg.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            agents.append(AgentName.from_str(part))
        except ValueError:
            print(f"Unknown agent: {part}")
            sys.exit(1)
    return agents
