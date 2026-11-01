"""Reusable history search functions backed by conversation mirrors."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Sequence
from typing import Final

from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.cli.session_auth import no_identity_refusal, resolve_cli_identity
from teleclaude.cli.tool_client import (
    NotAcceptedCause,
    exit_not_accepted,
    not_accepted_cause_text,
    print_run_again_when_not_accepted,
)
from teleclaude.config.machine import config
from teleclaude.constants import HistoryComputerSelector
from teleclaude.core.agents import AgentName
from teleclaude.core.command_dispatch import is_relay_failure_detail, is_remote_target
from teleclaude.history.fleet import select_history_fleet
from teleclaude.history.search_payload import HistorySearchPayload, HistorySearchRow
from teleclaude.history.service import build_history_search_payload, resolve_history_reach
from teleclaude.identity_reach import Reach
from teleclaude.types.commands import CommandType

_TARGET_FAILURE_TEMPLATE: Final = "[{target}] History search failed: {failure}"
_LOCAL_TARGET: Final = "local"

type _SearchFailure = tuple[BaseException, str | None]


def _print_results(
    search_term: str,
    results: list[HistorySearchRow],
    *,
    show_computer: bool,
    limit: int,
    excluded_workers: int = 0,
    json_output: bool = False,
) -> None:
    results = results[:limit]
    if json_output:
        print(json.dumps(results))
        return
    if not results:
        return
    print(f"\nSearch results for '{search_term}' ({len(results)} found):\n")

    if excluded_workers:
        print(f"Excluded focused-role matches: {excluded_workers}\n")

    for entry in results:
        tc_id = entry["tc_id"]
        native_id = entry["native_id"]
        if tc_id is not None:
            identifier_label = "tc_id:"
            identifier = tc_id
        else:
            identifier_label = "native_id:"
            identifier = native_id or ""
        computer = f"  {entry['computer']:<12}" if show_computer else ""
        print(
            f"{entry['timestamp']}  {entry['agent']:<7}{computer}  "
            f"{identifier_label:<10} {identifier:<36}  {entry['project']}"
        )
        topic = " ".join(entry["topic"].splitlines())
        print(f"    {topic}")


async def _search_targets(
    *,
    computers: Sequence[str | None],
    search_term: str,
    agents: Sequence[AgentName],
    limit: int,
    include_workers: bool,
    identity: str | None,
    project: str | None,
    reach: Reach | None,
    fleet: bool,
) -> tuple[
    list[tuple[HistorySearchPayload | BaseException, str | None]], list[str], APIError | None, list[str | None], bool
]:
    client = TelecAPIClient()
    skipped: list[str] = []
    roster_failure: APIError | None = None
    incomplete = False
    try:
        if fleet or any(is_remote_target(target, config.computer.name) for target in computers):
            await client.connect()
        if fleet:
            try:
                roster = await client.list_computers()
            except APIError as exc:
                roster_failure = exc
                roster = None
            selection = select_history_fleet(config.computer.name, roster)
            computers = selection.targets
            skipped = list(selection.skipped)
            incomplete = selection.incomplete
        agent_filter = ",".join(agent.value for agent in agents) if agents else "all"
        tasks: list[Awaitable[HistorySearchPayload]] = []
        for computer in computers:
            if not is_remote_target(computer, config.computer.name):
                assert reach is not None
                tasks.append(
                    asyncio.to_thread(
                        build_history_search_payload,
                        computer=config.computer.name,
                        query=search_term,
                        agents=agents,
                        limit=limit,
                        reach=reach,
                        include_workers=include_workers,
                        identity=identity,
                        project=project,
                    )
                )
            else:
                tasks.append(
                    client.search_history(
                        query=search_term,
                        agent=agent_filter,
                        limit=limit,
                        computer=computer,
                        include_workers=include_workers,
                        identity=identity,
                        project=project,
                    )
                )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return list(zip(results, computers, strict=True)), skipped, roster_failure, list(computers), incomplete
    finally:
        await client.close()


def display_combined_history(
    agents: list[AgentName],
    search_term: str = "",
    limit: int = 20,
    computers: Sequence[str] | None = None,
    include_workers: bool = False,
    identity: str | None = None,
    project: str | None = None,
    json_output: bool = False,
) -> None:
    """Search local mirrors and selected peers, expanding the fleet selector."""
    fleet = bool(computers and HistoryComputerSelector.ALL in computers)
    if fleet and len(computers or ()) != 1:
        print("Error: --computer all cannot be combined with named computers", file=sys.stderr)
        raise SystemExit(1)
    targets: Sequence[str | None] = computers if computers else [None]
    reach = None
    if fleet or any(not is_remote_target(computer, config.computer.name) for computer in targets):
        resolved_caller = resolve_cli_identity()
        reach = resolve_history_reach(resolved_caller.caller)
        if reach is None:
            print(f"Error: {no_identity_refusal(resolved_caller)}", file=sys.stderr)
            raise SystemExit(1)
    responses, skipped, roster_failure, searched, incomplete = asyncio.run(
        _search_targets(
            computers=targets,
            search_term=search_term,
            agents=agents,
            limit=limit,
            include_workers=include_workers,
            identity=identity,
            project=project,
            reach=reach,
            fleet=fleet,
        )
    )

    answered: list[HistorySearchPayload] = []
    failures: list[_SearchFailure] = []
    for response, computer in responses:
        if isinstance(response, BaseException):
            if not isinstance(response, APIError):
                raise response
            failures.append((response, computer))
        else:
            answered.append(response)

    refusal_cause = _first_not_accepted_cause(failures)
    if not answered and refusal_cause is not None and _every_failure_not_accepted(failures):
        exit_not_accepted(refusal_cause)

    for failure, computer in failures:
        print(
            _TARGET_FAILURE_TEMPLATE.format(target=computer or _LOCAL_TARGET, failure=_failure_text(failure)),
            file=sys.stderr,
        )
    for computer in skipped:
        print(_TARGET_FAILURE_TEMPLATE.format(target=computer, failure="offline; not searched"), file=sys.stderr)
    if incomplete:
        assert roster_failure is not None
        print(
            _TARGET_FAILURE_TEMPLATE.format(
                target="fleet", failure=f"could not enumerate computers: {_failure_text(roster_failure)}"
            ),
            file=sys.stderr,
        )
        print_run_again_when_not_accepted(_not_accepted_cause(roster_failure))
    if answered:
        _print_answers(
            answered,
            search_term=search_term,
            computers=[target for target in searched if target is not None] if fleet else computers,
            agents=agents,
            limit=limit,
            json_output=json_output,
        )
    if incomplete:
        raise SystemExit(1)
    if failures:
        print_run_again_when_not_accepted(refusal_cause)
        if not (answered and all(_is_peer_failure(failure, computer) for failure, computer in failures)):
            raise SystemExit(1)


def _not_accepted_cause(failure: BaseException) -> NotAcceptedCause | None:
    """Why this target's request was not accepted by the daemon, or ``None`` for any other failure."""
    return failure.not_accepted_cause if isinstance(failure, APIError) else None


def _first_not_accepted_cause(failures: list[_SearchFailure]) -> NotAcceptedCause | None:
    """The cause of the first request a draining or unreachable daemon did not accept."""
    return next((cause for failure, _ in failures if (cause := _not_accepted_cause(failure)) is not None), None)


def _every_failure_not_accepted(failures: list[_SearchFailure]) -> bool:
    """Whether the daemon accepted none of the failed requests."""
    return all(_not_accepted_cause(failure) is not None for failure, _ in failures)


def _failure_text(failure: BaseException) -> str:
    """The failure in words; a refusal or an unreachable daemon is described without its response body."""
    cause = _not_accepted_cause(failure)
    return str(failure) if cause is None else not_accepted_cause_text(cause)


def _is_peer_failure(failure: BaseException, computer: str | None) -> bool:
    """Whether the failure is the relay's own report that a read on the named peer computer failed."""
    return (
        isinstance(failure, APIError)
        and computer is not None
        and is_relay_failure_detail(failure.detail, command=CommandType.RELAY_REQUEST.value, computer=computer)
    )


def _print_answers(
    answered: list[HistorySearchPayload],
    *,
    search_term: str,
    computers: Sequence[str] | None,
    agents: Sequence[AgentName],
    limit: int,
    json_output: bool,
) -> None:
    """Print the rows every answering target returned, merged newest first."""
    results: list[HistorySearchRow] = []
    excluded_workers = 0
    for payload in answered:
        results.extend(payload["rows"])
        excluded_workers += payload["excluded_workers"]
    if not results:
        if json_output:
            print(json.dumps([]))
            return
        scope = ", ".join(computers) if computers else ", ".join(agent.value for agent in agents)
        print(f"No conversations found matching '{search_term}' across {scope}")
        return
    results.sort(key=lambda entry: entry["sort_timestamp"], reverse=True)
    _print_results(
        search_term,
        results,
        show_computer=bool(computers),
        limit=limit,
        excluded_workers=excluded_workers,
        json_output=json_output,
    )


def parse_agents(agent_arg: str) -> list[AgentName]:
    """Parse agent argument into list of AgentName."""
    agent_arg = agent_arg.strip().lower()
    if agent_arg == "all":
        return list(AgentName)

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
