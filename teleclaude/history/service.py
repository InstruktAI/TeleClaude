"""History search service shared by local API and peer transport boundaries."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from teleclaude.core.agents import AgentName
from teleclaude.core.db._sync import get_session_ids_by_native_sync
from teleclaude.mirrors.store import MirrorSearchResult, search_mirrors
from teleclaude.paths import MAIN_DB_PATH


class HistorySearchRow(TypedDict):
    """Wire-safe history search row with both identity namespaces."""

    sort_timestamp: str
    timestamp: str
    computer: str
    agent: str
    project: str
    topic: str
    tc_id: str | None
    native_id: str | None


class HistorySearchPayload(TypedDict):
    """Search rows plus the count withheld by the worker default."""

    computer: str
    rows: list[HistorySearchRow]
    excluded_workers: int


def parse_history_agents(agent_filter: str) -> list[AgentName]:
    """Parse a comma-separated agent filter for service boundaries."""
    if agent_filter == "all":
        return list(AgentName)
    return [AgentName(value.strip().lower()) for value in agent_filter.split(",") if value.strip()]


def history_results_to_rows(results: Sequence[MirrorSearchResult]) -> list[HistorySearchRow]:
    """Attach TeleClaude ids to mirror-native search rows."""
    native_ids = [result.session_id for result in results if result.session_id is not None]
    tc_ids = get_session_ids_by_native_sync(str(MAIN_DB_PATH), native_ids)
    return [
        HistorySearchRow(
            sort_timestamp=result.sort_timestamp,
            timestamp=result.timestamp,
            computer=result.computer,
            agent=result.agent,
            project=result.project,
            topic=result.topic,
            tc_id=tc_ids.get(result.session_id) if result.session_id is not None else None,
            native_id=result.session_id,
        )
        for result in results
    ]


def build_history_search_payload(
    *,
    computer: str,
    query: str,
    agents: Sequence[AgentName],
    limit: int,
    caller_email: str | None,
    caller_role: str | None,
    include_workers: bool,
    identity: str | None,
    project: str | None,
) -> HistorySearchPayload:
    """Search local mirrors and return the federated wire contract."""
    page = search_mirrors(
        query,
        agents,
        limit=limit,
        caller_email=caller_email,
        caller_role=caller_role,
        include_workers=include_workers,
        identity=identity,
        project=project,
    )
    return HistorySearchPayload(
        computer=computer,
        rows=history_results_to_rows(page.results),
        excluded_workers=page.excluded_workers,
    )
