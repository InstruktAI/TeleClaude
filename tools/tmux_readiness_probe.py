#!/usr/bin/env python3
"""Probe tmux readiness assumptions for TeleClaude agent startup."""
# pylint: disable=missing-class-docstring,missing-function-docstring,too-many-instance-attributes,too-many-arguments,too-many-locals,too-many-branches

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import pwd
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.core.agents import AgentName
from teleclaude.core.tmux_bridge import collect_pane_snapshot, get_current_command
from teleclaude.core.tmux_bridge._subprocess import SubprocessTimeoutError


@dataclass(frozen=True)
class CommandTransition:
    elapsed_s: float
    session_exists: bool
    pane_dead: bool
    current_command: str | None
    non_shell_process: bool
    marker_present: bool
    tail_excerpt: str


def _shell_name() -> str:
    shell = os.environ.get("SHELL")
    if shell:
        return Path(shell).name.lower()
    return Path(str(pwd.getpwuid(os.getuid()).pw_shell)).name.lower()


def _tmux_name(args: argparse.Namespace) -> str:
    tmux_session = getattr(args, "tmux_session", None)
    if isinstance(tmux_session, str) and tmux_session:
        return tmux_session
    session_id = getattr(args, "session_id", None)
    if isinstance(session_id, str) and session_id:
        return f"tc_{session_id}"
    raise ValueError("either --tmux-session or --session-id is required")


@dataclass(frozen=True)
class ProbeSnapshot:
    ts: float
    tmux_session: str
    agent: str
    shell_name: str
    session_exists: bool
    pane_dead: bool
    current_command: str | None
    non_shell_process: bool
    marker: str
    marker_present: bool
    ready_command_and_marker: bool
    ready_marker_only: bool
    tail_excerpt: str


@dataclass(frozen=True)
class StartupProbeResult:
    agent: str
    session_id: str
    tmux_session_name: str
    first_non_shell_at_s: float | None
    first_marker_at_s: float | None
    first_command_and_marker_at_s: float | None
    first_settle_and_marker_at_s: float | None
    timed_out: bool
    final_session_exists: bool
    final_pane_dead: bool
    final_current_command: str | None
    final_marker_present: bool
    final_tail_excerpt: str
    command_transitions: list[CommandTransition]


async def _snapshot(tmux_session: str, agent: str, shell_name: str, tail_chars: int) -> ProbeSnapshot:
    try:
        pane = await collect_pane_snapshot(tmux_session, capture_lines=tail_chars)
        current_command = await get_current_command(tmux_session) if pane.session_exists else None
        output = pane.output
    except (OSError, ValueError, SubprocessTimeoutError):
        pane = None
        current_command = None
        output = ""
    marker = AgentName.from_str(agent).prompt_marker
    tail = output[-tail_chars:] if tail_chars > 0 else output
    non_shell_process = bool(current_command and current_command.lower() != shell_name)
    marker_present = marker in tail
    return ProbeSnapshot(
        ts=time.time(),
        tmux_session=tmux_session,
        agent=agent,
        shell_name=shell_name,
        session_exists=pane.session_exists if pane is not None else False,
        pane_dead=pane.pane_dead if pane is not None else False,
        current_command=current_command,
        non_shell_process=non_shell_process,
        marker=marker,
        marker_present=marker_present,
        ready_command_and_marker=non_shell_process and marker_present,
        ready_marker_only=marker_present,
        tail_excerpt=tail[-tail_chars:] if tail_chars > 0 else tail,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=[agent.value for agent in AgentName])
    parser.add_argument(
        "--agents",
        nargs="+",
        choices=[agent.value for agent in AgentName],
        help="Spawn and probe fresh sessions for these agents",
    )
    parser.add_argument("--tmux-session", help="Exact tmux session name, e.g. tc_<uuid>")
    parser.add_argument("--session-id", help="TeleClaude session id suffix, without tc_ prefix")
    parser.add_argument("--project", help="Project path for spawned sessions")
    parser.add_argument("--mode", default="slow", choices=["fast", "med", "slow"])
    parser.add_argument(
        "--message",
        default="Readiness probe: reply with exactly READY.",
        help="Startup message for spawned sessions",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Startup probe timeout in seconds")
    parser.add_argument("--tail-chars", type=int, default=800, help="Pane tail excerpt size to include")
    parser.add_argument("--watch", type=float, default=0.0, help="Watch for N seconds instead of one snapshot")
    parser.add_argument("--interval", type=float, default=0.5, help="Polling interval while watching")
    parser.add_argument("--keep", action="store_true", help="Keep spawned sessions instead of ending them")
    parser.add_argument(
        "--cleanup-all",
        action="store_true",
        help="End spawned sessions even when they timed out (default keeps timed-out sessions for inspection)",
    )
    parser.add_argument("--jsonl", action="store_true", help="Emit one JSON object per line while watching")
    return parser


async def _spawn_session(agent: str, project: str, message: str, mode: str) -> tuple[str, str]:
    client = TelecAPIClient()
    await client.connect()
    try:
        response = await client.create_session(
            computer="local",
            project_path=project,
            agent=agent,
            thinking_mode=mode,
            message=message,
            skip_listener_registration=True,
        )
        return response.session_id, response.tmux_session_name
    finally:
        await client.close()


async def _end_session(session_id: str) -> None:
    client = TelecAPIClient()
    await client.connect()
    try:
        await client.end_session(session_id, "local")
    finally:
        await client.close()


async def _probe_startup(
    *,
    agent: str,
    tmux_session: str,
    session_id: str,
    timeout: float,
    interval: float,
    tail_chars: int,
    shell_name: str,
    jsonl: bool,
) -> StartupProbeResult:
    deadline = time.monotonic() + timeout
    start_time = time.monotonic()
    first_non_shell_at_s: float | None = None
    first_marker_at_s: float | None = None
    first_command_and_marker_at_s: float | None = None
    first_settle_and_marker_at_s: float | None = None
    last_digest: str | None = None
    quiet_since: float | None = None
    final_snapshot: ProbeSnapshot | None = None
    last_command: str | None = None
    last_marker_present: bool | None = None
    last_session_exists: bool | None = None
    last_pane_dead: bool | None = None
    command_transitions: list[CommandTransition] = []

    while time.monotonic() < deadline:
        snap = await _snapshot(tmux_session, agent, shell_name, tail_chars)
        final_snapshot = snap
        now = time.monotonic()
        elapsed = now - start_time
        digest = hashlib.sha256(snap.tail_excerpt.encode("utf-8", errors="replace")).hexdigest()

        if digest != last_digest:
            quiet_since = now
            last_digest = digest

        if snap.non_shell_process and first_non_shell_at_s is None:
            first_non_shell_at_s = elapsed
        if snap.marker_present and first_marker_at_s is None:
            first_marker_at_s = elapsed
        if snap.ready_command_and_marker and first_command_and_marker_at_s is None:
            first_command_and_marker_at_s = elapsed
        if (
            quiet_since is not None
            and (now - quiet_since) >= 1.0
            and snap.marker_present
            and first_settle_and_marker_at_s is None
        ):
            first_settle_and_marker_at_s = elapsed

        if (
            snap.current_command != last_command
            or snap.marker_present != last_marker_present
            or snap.session_exists != last_session_exists
            or snap.pane_dead != last_pane_dead
        ):
            command_transitions.append(
                CommandTransition(
                    elapsed_s=round(elapsed, 3),
                    session_exists=snap.session_exists,
                    pane_dead=snap.pane_dead,
                    current_command=snap.current_command,
                    non_shell_process=snap.non_shell_process,
                    marker_present=snap.marker_present,
                    tail_excerpt=snap.tail_excerpt,
                )
            )
            last_command = snap.current_command
            last_marker_present = snap.marker_present
            last_session_exists = snap.session_exists
            last_pane_dead = snap.pane_dead

        if jsonl:
            print(
                json.dumps(
                    {
                        "event": "tick",
                        "elapsed_s": round(elapsed, 3),
                        **asdict(snap),
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )

        if first_command_and_marker_at_s is not None and first_settle_and_marker_at_s is not None:
            break
        await asyncio.sleep(max(0.1, interval))

    if final_snapshot is None:
        raise RuntimeError(f"no probe snapshots captured for {tmux_session}")

    return StartupProbeResult(
        agent=agent,
        session_id=session_id,
        tmux_session_name=tmux_session,
        first_non_shell_at_s=None if first_non_shell_at_s is None else round(first_non_shell_at_s, 3),
        first_marker_at_s=None if first_marker_at_s is None else round(first_marker_at_s, 3),
        first_command_and_marker_at_s=(
            None if first_command_and_marker_at_s is None else round(first_command_and_marker_at_s, 3)
        ),
        first_settle_and_marker_at_s=(
            None if first_settle_and_marker_at_s is None else round(first_settle_and_marker_at_s, 3)
        ),
        timed_out=first_command_and_marker_at_s is None,
        final_session_exists=final_snapshot.session_exists,
        final_pane_dead=final_snapshot.pane_dead,
        final_current_command=final_snapshot.current_command,
        final_marker_present=final_snapshot.marker_present,
        final_tail_excerpt=final_snapshot.tail_excerpt,
        command_transitions=command_transitions,
    )


async def _run(args: argparse.Namespace) -> int:
    shell_name = _shell_name()
    if args.agents:
        if not args.project:
            raise ValueError("--project is required when using --agents")

        sessions: list[tuple[str, str, str]] = []
        for agent in args.agents:
            session_id, tmux_session = await _spawn_session(agent, args.project, args.message, args.mode)
            sessions.append((agent, session_id, tmux_session))

        results: list[StartupProbeResult] | None = None
        try:
            results = await asyncio.gather(
                *[
                    _probe_startup(
                        agent=agent,
                        tmux_session=tmux_session,
                        session_id=session_id,
                        timeout=args.timeout,
                        interval=args.interval,
                        tail_chars=args.tail_chars,
                        shell_name=shell_name,
                        jsonl=args.jsonl,
                    )
                    for agent, session_id, tmux_session in sessions
                ]
            )
        finally:
            if not args.keep:
                sessions_to_end: list[str]
                if results is None or args.cleanup_all:
                    sessions_to_end = [session_id for _agent, session_id, _tmux_session in sessions]
                else:
                    sessions_to_end = [result.session_id for result in results if not result.timed_out]
                if sessions_to_end:
                    await asyncio.gather(*[_end_session(session_id) for session_id in sessions_to_end])

        print(json.dumps([asdict(result) for result in results], ensure_ascii=True, indent=2))
        return 0

    if not args.agent:
        raise ValueError("--agent is required when probing an existing session")

    tmux_session = _tmux_name(args)
    end_at = time.monotonic() + max(0.0, args.watch)
    while True:
        snap = await _snapshot(tmux_session, args.agent, shell_name, args.tail_chars)
        payload = asdict(snap)
        if args.jsonl or args.watch > 0:
            print(json.dumps(payload, ensure_ascii=True), flush=True)
        else:
            print(json.dumps(payload, ensure_ascii=True, indent=2), flush=True)
        if args.watch <= 0:
            return 0
        if time.monotonic() >= end_at:
            return 0
        await asyncio.sleep(max(0.1, args.interval))


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
