"""telec: terminal CLI for starting TeleClaude agent sessions."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, TextIO, cast

from teleclaude.config import config
from teleclaude.core import session_cleanup
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.agents import normalize_agent_name
from teleclaude.core.db import db, get_session_id_by_field_sync
from teleclaude.core.events import TeleClaudeEvents, parse_command_string
from teleclaude.core.models import MessageMetadata, ThinkingMode
from teleclaude.core.terminal_events import (
    TERMINAL_METADATA_KEY,
    TerminalEventMetadata,
    TerminalOutboxMetadata,
    TerminalOutboxPayload,
    TerminalOutboxResponse,
)
from teleclaude.core.terminal_sessions import terminal_tmux_name_for_session

if TYPE_CHECKING:
    from teleclaude.core.models import Session

_UNSET = object()

_TERMINAL_OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS terminal_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    metadata TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    next_attempt_at TEXT DEFAULT CURRENT_TIMESTAMP,
    attempt_count INTEGER DEFAULT 0,
    last_error TEXT,
    delivered_at TEXT,
    locked_at TEXT,
    response TEXT
);
CREATE INDEX IF NOT EXISTS idx_terminal_outbox_pending ON terminal_outbox(delivered_at, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_terminal_outbox_request ON terminal_outbox(request_id);
"""

TELEC_OUTBOX_POLL_INTERVAL_S = float(os.getenv("TELEC_OUTBOX_POLL_INTERVAL_S", "0.05"))
TELEC_OUTBOX_RESPONSE_TIMEOUT_S = float(os.getenv("TELEC_OUTBOX_RESPONSE_TIMEOUT_S", "10"))


@dataclass
class TelecCommand:
    action: str  # "start" | "resume"
    agent: str | None
    args: list[str]
    session_id: str | None


@dataclass
class SessionListEntry:
    index: int
    session_id: str
    title: str
    origin_adapter: str
    tmux_session_name: str
    working_directory: str | None
    last_activity: datetime | None
    created_at: datetime | None
    active_agent: str | None
    thinking_mode: str | None
    tmux_ready: bool


def _usage() -> str:
    return (
        "Usage:\n"
        "  telec                      # open session picker\n"
        "  telec /list                # list sessions\n"
        "  telec /new_session          # create & attach new tmux session\n"
        "  telec /claude fast [prompt]\n"
        "  telec /gemini med [prompt]\n"
        "  telec /codex slow [prompt]\n"
        "  telec /agent <claude|gemini|codex> <slow|med|fast> [prompt]\n"
        "  telec /agent_resume  # resume latest for active agent\n"
        "  telec /agent_resume <teleclaude_session_id>\n"
    )


def _resolve_tty() -> str | None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream_typed = cast(TextIO, stream)
            if stream_typed.isatty():
                tty_path = os.ttyname(stream_typed.fileno())
                if Path(tty_path).exists():
                    return tty_path
        except Exception:
            continue
    return None


def _split_thinking_mode(args: Iterable[str], default_mode: str, agent: str) -> tuple[str, list[str]]:
    remaining = list(args)
    thinking_mode = default_mode
    valid_modes = {mode.value for mode in ThinkingMode}
    if remaining and remaining[0] in valid_modes:
        thinking_mode = remaining.pop(0)

    if thinking_mode == ThinkingMode.DEEP.value and agent != "codex":
        raise ValueError("deep is only supported for codex")
    return thinking_mode, remaining


def _parse_agent_args(
    agent_name: str,
    args: list[str],
    stored_mode: str | None,
) -> tuple[str, list[str]]:
    default_mode = stored_mode or ThinkingMode.SLOW.value
    return _split_thinking_mode(args, default_mode, agent_name)


_SLASH_COMMANDS = (
    "/list",
    "/new_session",
    "/rename",
    "/agent",
    "/agent_resume",
    "/claude",
    "/gemini",
    "/codex",
)
_AGENTS = ("claude", "gemini", "codex")
_MODES: tuple[str, ...] = ("fast", "med", "slow")


def _completion_candidates(tokens: list[str]) -> list[str]:
    if tokens == [""]:
        tokens = []
    if not tokens:
        return list(_SLASH_COMMANDS)

    last = tokens[-1]
    prev = tokens[-2] if len(tokens) >= 2 else ""

    if last.startswith("/"):
        return [cmd for cmd in _SLASH_COMMANDS if cmd.startswith(last)]

    if prev in {"/claude", "/gemini", "/codex"}:
        modes = list(_MODES)
        if prev == "/codex":
            modes.append("deep")
        return [mode for mode in modes if mode.startswith(last)]

    if prev == "/agent":
        return [agent for agent in _AGENTS if agent.startswith(last)]

    if len(tokens) >= 3 and tokens[-3] == "/agent":
        modes = list(_MODES)
        if tokens[-2] == "codex":
            modes.append("deep")
        return [mode for mode in modes if mode.startswith(last)]

    if prev == "/agent_resume":
        db_path = config.database.path
        conn = sqlite3.connect(db_path, timeout=1.0)
        try:
            conn.execute("PRAGMA busy_timeout = 1000")
            entries = _load_sessions(conn)
        finally:
            conn.close()
        ids = [entry.session_id[:8] for entry in entries]
        idxs = [str(entry.index) for entry in entries]
        tmux_names = [entry.tmux_session_name for entry in entries if entry.tmux_session_name]
        options = ids + idxs + tmux_names
        return [opt for opt in options if opt.startswith(last)]

    if last == "" and prev == "telec":
        return list(_SLASH_COMMANDS)

    return []


def _complete_from_env() -> None:
    line = os.environ.get("COMP_LINE", "")
    point_raw = os.environ.get("COMP_POINT")
    point = int(point_raw) if point_raw and point_raw.isdigit() else len(line)
    line = line[:point]
    try:
        tokens = shlex.split(line)
    except ValueError:
        tokens = re.split(r"\\s+", line.strip())
    if line.endswith(" "):
        tokens.append("")
    # Drop program name
    if tokens and tokens[0] == "telec":
        tokens = tokens[1:]
    for item in _completion_candidates(tokens):
        print(item)


def parse_telec_command(argv: list[str]) -> TelecCommand:
    if not argv:
        raise ValueError(_usage())

    if not argv[0].startswith("/"):
        raise ValueError(_usage())

    command_str = " ".join(argv)
    cmd_name, args = parse_command_string(command_str)
    if not cmd_name:
        raise ValueError(_usage())

    if cmd_name in {"list", "list_sessions"}:
        return TelecCommand(action="list", agent=None, args=args, session_id=None)

    if cmd_name == "new_session":
        return TelecCommand(action="new_session", agent=None, args=args, session_id=None)

    if cmd_name in {"claude", "gemini", "codex"}:
        return TelecCommand(action="start", agent=cmd_name, args=args, session_id=None)

    if cmd_name == "agent":
        if not args:
            raise ValueError(_usage())
        return TelecCommand(action="start", agent=args[0], args=args[1:], session_id=None)

    if cmd_name == "agent_resume":
        session_id = args[0] if args else None
        return TelecCommand(action="resume", agent=None, args=args[1:] if args else [], session_id=session_id)

    raise ValueError(_usage())


def _ensure_terminal_outbox(conn: sqlite3.Connection) -> None:
    conn.executescript(_TERMINAL_OUTBOX_SCHEMA)


def _metadata_to_dict(metadata: MessageMetadata) -> TerminalOutboxMetadata:
    return cast(TerminalOutboxMetadata, asdict(metadata))


def _build_terminal_metadata(
    *,
    tty_path: str,
    parent_pid: int,
    cols: int,
    rows: int,
    cwd: str,
    auto_command: str | None = None,
) -> MessageMetadata:
    terminal_meta = TerminalEventMetadata(
        tty_path=tty_path,
        parent_pid=parent_pid if parent_pid > 1 else None,
        terminal_size=f"{cols}x{rows}",
    )
    channel_metadata = terminal_meta.to_channel_metadata()
    channel_metadata_dict: dict[str, object] | None = None  # noqa: loose-dict - MessageMetadata contract
    if channel_metadata:
        channel_metadata_dict = {}
        channel_metadata_dict[TERMINAL_METADATA_KEY] = channel_metadata[TERMINAL_METADATA_KEY]
    return MessageMetadata(
        adapter_type="terminal",
        project_dir=cwd,
        channel_metadata=channel_metadata_dict,
        auto_command=auto_command,
    )


def _enqueue_terminal_event(
    db_path: str,
    request_id: str,
    event_type: str,
    payload: TerminalOutboxPayload,
    metadata: MessageMetadata,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    payload_json = json.dumps(payload)
    metadata_json = json.dumps(_metadata_to_dict(metadata))

    conn = sqlite3.connect(db_path, timeout=1.0)
    try:
        conn.execute("PRAGMA busy_timeout = 1000")
        _ensure_terminal_outbox(conn)
        conn.execute(
            """
            INSERT INTO terminal_outbox (
                request_id, event_type, payload, metadata, created_at, next_attempt_at, attempt_count
            ) VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (request_id, event_type, payload_json, metadata_json, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _wait_for_terminal_response(
    db_path: str,
    request_id: str,
    *,
    timeout_s: float = TELEC_OUTBOX_RESPONSE_TIMEOUT_S,
    poll_interval_s: float = TELEC_OUTBOX_POLL_INTERVAL_S,
) -> TerminalOutboxResponse:
    deadline = time.monotonic() + timeout_s
    conn = sqlite3.connect(db_path, timeout=1.0)
    conn.isolation_level = None
    try:
        conn.execute("PRAGMA busy_timeout = 1000")
        while time.monotonic() < deadline:
            cursor = conn.execute(
                "SELECT response FROM terminal_outbox WHERE request_id = ?",
                (request_id,),
            )
            row = cast(tuple[object] | None, cursor.fetchone())
            if row and row[0]:
                raw = row[0]
                if isinstance(raw, str):
                    parsed = cast(object, json.loads(raw))
                    if isinstance(parsed, dict):
                        return cast(TerminalOutboxResponse, parsed)
                raise ValueError("terminal outbox response is invalid")
            time.sleep(poll_interval_s)
    finally:
        conn.close()

    raise TimeoutError("Timed out waiting for terminal response")


def _dispatch_terminal_event(
    db_path: str,
    event_type: str,
    payload: TerminalOutboxPayload,
    metadata: MessageMetadata,
    *,
    wait_for_response: bool = True,
) -> TerminalOutboxResponse | None:
    request_id = str(uuid.uuid4())
    _enqueue_terminal_event(db_path, request_id, event_type, payload, metadata)
    if not wait_for_response:
        return None
    return _wait_for_terminal_response(db_path, request_id)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _get_session_entry_by_id(db_path: str, session_id: str) -> SessionListEntry | None:
    conn = sqlite3.connect(db_path, timeout=1.0)
    try:
        conn.execute("PRAGMA busy_timeout = 1000")
        entries = _load_sessions(conn)
    finally:
        conn.close()
    for entry in entries:
        if entry.session_id == session_id:
            return entry
    return None


def _find_session_id_for_tty(db_path: str, tty_path: str) -> str | None:
    session_id = get_session_id_by_field_sync(db_path, "native_tty_path", tty_path)
    if session_id:
        return session_id
    return get_session_id_by_field_sync(db_path, "tmux_tty_path", tty_path)


def _wait_for_tmux_session(session_name: str, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _tmux_session_exists(session_name):
            return True
        time.sleep(0.1)
    return False


def _tmux_session_exists(name: str) -> bool:
    if not name or not shutil.which("tmux"):
        return False
    result = subprocess.run(
        ["tmux", "has-session", "-t", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _load_sessions(conn: sqlite3.Connection) -> list[SessionListEntry]:
    cursor = conn.execute(
        """
        SELECT session_id, title, origin_adapter, tmux_session_name,
               working_directory, last_activity, created_at, active_agent, thinking_mode
        FROM sessions
        ORDER BY last_activity DESC
        """
    )
    rows = cast(list[tuple[object, ...]], cursor.fetchall())
    entries: list[SessionListEntry] = []
    for idx, row in enumerate(rows, start=1):
        session_id = str(row[0])
        title = str(row[1]) if row[1] else "(untitled)"
        origin_adapter = str(row[2]) if row[2] else "unknown"
        tmux_name = str(row[3]) if row[3] else ""
        working_directory = str(row[4]) if row[4] else None
        last_activity = _parse_datetime(row[5])
        created_at = _parse_datetime(row[6])
        active_agent = str(row[7]) if row[7] else None
        thinking_mode = str(row[8]) if row[8] else None
        entries.append(
            SessionListEntry(
                index=idx,
                session_id=session_id,
                title=title,
                origin_adapter=origin_adapter,
                tmux_session_name=tmux_name,
                working_directory=working_directory,
                last_activity=last_activity,
                created_at=created_at,
                active_agent=active_agent,
                thinking_mode=thinking_mode,
                tmux_ready=_tmux_session_exists(tmux_name),
            )
        )
    return entries


def _resolve_session_selection(selection: str, entries: list[SessionListEntry]) -> SessionListEntry:
    if not selection:
        raise ValueError("No session selected")
    if selection.isdigit():
        idx = int(selection)
        match = [entry for entry in entries if entry.index == idx]
        if match:
            return match[0]
        raise ValueError(f"No session at index {idx}")

    selection_lower = selection.lower()
    matches = [
        entry
        for entry in entries
        if entry.session_id.lower().startswith(selection_lower)
        or entry.tmux_session_name.lower().startswith(selection_lower)
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"No session matching '{selection}'")
    raise ValueError(f"Multiple sessions match '{selection}'")


def _format_timestamp(value: datetime | None) -> str:
    if not value:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M")


def _resolve_tmux_name(entry: SessionListEntry) -> str:
    if entry.tmux_session_name:
        return entry.tmux_session_name
    if entry.origin_adapter == "terminal":
        return terminal_tmux_name_for_session(entry.session_id)
    raise ValueError("Session has no tmux session name")


def _print_session_table(entries: list[SessionListEntry]) -> None:
    header = f"{'Idx':>3}  {'Last Active':<16}  {'ID':<8}  {'Agent':<6}  {'Mode':<4}  Title"
    print(header)
    print("-" * len(header))
    for entry in entries:
        agent = entry.active_agent or "—"
        mode = entry.thinking_mode or "—"
        last = _format_timestamp(entry.last_activity or entry.created_at)
        title = entry.title
        print(f"{entry.index:>3}  {last:<16}  {entry.session_id[:8]:<8}  {agent:<6}  {mode:<4}  {title}")


def _list_sessions(db_path: str) -> None:
    conn = sqlite3.connect(db_path, timeout=1.0)
    try:
        conn.execute("PRAGMA busy_timeout = 1000")
        entries = _load_sessions(conn)
    finally:
        conn.close()
    if not entries:
        print("No sessions found.")
        return
    _print_session_table(entries)


def _run_session_picker(db_path: str) -> SessionListEntry | None:
    import curses

    header_lines = [
        "████████╗███████╗██╗     ███████╗ ██████╗██╗      █████╗ ██╗   ██╗██████╗ ███████╗",
        "╚══██╔══╝██╔════╝██║     ██╔════╝██╔════╝██║     ██╔══██╗██║   ██║██╔══██╗██╔════╝",
        "   ██║   █████╗  ██║     █████╗  ██║     ██║     ███████║██║   ██║██║  ██║█████╗  ",
        "   ██║   ██╔══╝  ██║     ██╔══╝  ██║     ██║     ██╔══██║██║   ██║██║  ██║██╔══╝  ",
        "   ██║   ███████╗███████╗███████╗╚██████╗███████╗██║  ██║╚██████╔╝██████╔╝███████╗",
        "   ╚═╝   ╚══════╝╚══════╝╚══════╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝",
        "- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -",
    ]

    def _load() -> list[SessionListEntry]:
        conn = sqlite3.connect(db_path, timeout=1.0)
        try:
            conn.execute("PRAGMA busy_timeout = 1000")
            return _load_sessions(conn)
        finally:
            conn.close()

    def _filter(entries: list[SessionListEntry], text: str) -> list[SessionListEntry]:
        if not text:
            return entries
        needle = text.lower()
        return [
            entry
            for entry in entries
            if needle in entry.title.lower()
            or needle in entry.session_id.lower()
            or needle in entry.tmux_session_name.lower()
        ]

    def _ui(stdscr: "curses.window") -> SessionListEntry | None:
        curses.curs_set(0)
        use_colors = False
        agent_colors: dict[str, int] = {}
        agent_attrs: dict[str, int] = {}
        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
            except Exception:
                pass
            colors_available = cast(int, getattr(curses, "COLORS", 0))
            use_extended = bool(colors_available >= 256)
            # Claude: terra/brown, Codex: light grey, Gemini: pink
            claude_color: int = 130 if use_extended else int(curses.COLOR_RED)
            codex_color: int = 250 if use_extended else int(curses.COLOR_WHITE)
            gemini_color: int = 205 if use_extended else int(curses.COLOR_MAGENTA)
            agent_colors = {
                "claude": 1,
                "codex": 2,
                "gemini": 3,
            }
            curses.init_pair(agent_colors["claude"], claude_color, -1)
            curses.init_pair(agent_colors["codex"], codex_color, -1)
            curses.init_pair(agent_colors["gemini"], gemini_color, -1)
            agent_attrs = {
                "claude": curses.color_pair(agent_colors["claude"]),
                "codex": curses.color_pair(agent_colors["codex"]) | (0 if use_extended else int(curses.A_BOLD)),
                "gemini": curses.color_pair(agent_colors["gemini"]),
            }
            use_colors = True

        selected = 0
        filter_text = ""
        entries = _load()
        while True:
            filtered = _filter(entries, filter_text)
            if selected >= len(filtered):
                selected = max(0, len(filtered) - 1)

            stdscr.erase()
            height, width = stdscr.getmaxyx()
            for row_idx, line in enumerate(header_lines):
                stdscr.addstr(row_idx, 0, line[:width])

            table_header_row = len(header_lines)
            stdscr.addstr(
                table_header_row,
                0,
                "Idx  Last Active        ID       Agent  Mode  Title"[:width],
            )
            stdscr.hline(table_header_row + 1, 0, ord("-"), max(0, width - 1))

            header_block = len(header_lines) + 2
            footer_block = 2
            view_height = max(0, height - header_block - footer_block)
            start = 0
            if selected >= view_height:
                start = selected - view_height + 1
            for i, entry in enumerate(filtered[start : start + view_height]):
                row_idx = start + i
                last = _format_timestamp(entry.last_activity or entry.created_at)
                line = (
                    f"{entry.index:>3}  {last:<16}  {entry.session_id[:8]:<8}  "
                    f"{(entry.active_agent or '—'):<6}  {(entry.thinking_mode or '—'):<4}  {entry.title}"
                )
                row_y = table_header_row + 2 + i
                row_attr = curses.A_NORMAL
                if use_colors:
                    agent_key = (entry.active_agent or "").lower()
                    row_attr |= agent_attrs.get(agent_key, 0)
                if row_idx == selected:
                    row_attr |= curses.A_REVERSE
                stdscr.attron(row_attr)
                stdscr.addstr(row_y, 0, line[:width])
                stdscr.attroff(row_attr)

            footer = "↑↓ move  Enter attach  / filter  r refresh  q quit"
            stdscr.addstr(height - 2, 0, footer[:width])
            if filter_text:
                stdscr.addstr(height - 1, 0, f"filter: {filter_text}"[:width])
            else:
                stdscr.addstr(height - 1, 0, "filter: (none)"[:width])
            stdscr.refresh()

            key = stdscr.getch()
            if key in (ord("q"), 27):
                return None
            if key in (ord("r"),):
                entries = _load()
                continue
            if key in (curses.KEY_UP, ord("k")):
                selected = max(0, selected - 1)
                continue
            if key in (curses.KEY_DOWN, ord("j")):
                selected = min(max(0, len(filtered) - 1), selected + 1)
                continue
            if key in (ord("/"),):
                curses.echo()
                stdscr.addstr(height - 1, 0, "filter: ")
                stdscr.clrtoeol()
                filter_text = stdscr.getstr(height - 1, len("filter: ")).decode("utf-8")
                curses.noecho()
                selected = 0
                continue
            if key in (curses.KEY_ENTER, 10, 13):
                if filtered:
                    return filtered[selected]
                continue

        return None

    return curses.wrapper(_ui)


def _terminal_size() -> tuple[int, int]:
    size = shutil.get_terminal_size((160, 80))
    return size.columns, size.lines


def _attach_tmux(session_name: str) -> None:
    if os.getenv("TMUX"):
        os.execvp("tmux", ["tmux", "switch-client", "-t", session_name])
    os.execvp("tmux", ["tmux", "attach-session", "-t", session_name])


def _select_session_entry(db_path: str, selection: str | None) -> SessionListEntry | None:
    if not selection:
        return _run_session_picker(db_path)
    conn = sqlite3.connect(db_path, timeout=1.0)
    try:
        conn.execute("PRAGMA busy_timeout = 1000")
        entries = _load_sessions(conn)
    finally:
        conn.close()
    return _resolve_session_selection(selection, entries)


def _attach_session_entry(entry: SessionListEntry) -> None:
    tmux_name = _resolve_tmux_name(entry)

    if not shutil.which("tmux"):
        raise ValueError("tmux is required for terminal sessions")

    if not _wait_for_tmux_session(tmux_name):
        raise ValueError(f"tmux session {tmux_name} not found")

    _attach_tmux(tmux_name)


class _CleanupAdapterClient(AdapterClient):
    async def delete_channel(self, session: "Session") -> bool:
        _ = session
        return True


def _cleanup_stale_on_startup() -> None:
    if not shutil.which("tmux"):
        return

    async def _run() -> None:
        await db.initialize()
        try:
            client = _CleanupAdapterClient()
            await session_cleanup.cleanup_all_stale_sessions(client)
            await session_cleanup.cleanup_orphan_tmux_sessions()
            await session_cleanup.cleanup_orphan_workspaces()
            await session_cleanup.cleanup_orphan_mcp_wrappers()
            await db.cleanup_stale_voice_assignments()
        finally:
            await db.close()

    try:
        asyncio.run(_run())
    except Exception as exc:
        sys.stderr.write(f"telec: cleanup skipped ({exc})\n")


def _main_impl() -> None:
    argv = sys.argv[1:]
    db_path = config.database.path

    if os.getenv("TELEC_COMPLETE") == "1":
        _complete_from_env()
        return

    _cleanup_stale_on_startup()

    if not argv:
        selection = None
        if argv and len(argv) > 1:
            selection = argv[1]
        try:
            entry = _select_session_entry(db_path, selection)
        except ValueError as exc:
            sys.stderr.write(f"telec error: {exc}\n")
            sys.exit(1)
        if not entry:
            return
        try:
            _attach_session_entry(entry)
        except ValueError as exc:
            sys.stderr.write(f"telec error: {exc}\n")
            sys.exit(1)
        return

    try:
        parsed = parse_telec_command(argv)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(1)

    if parsed.action == "list":
        _list_sessions(db_path)
        return

    tty_path = _resolve_tty()
    if not tty_path:
        sys.stderr.write("telec: could not resolve a controlling TTY\n")
        sys.exit(1)

    parent_pid = os.getppid()
    cwd = os.getcwd()
    cols, rows = _terminal_size()

    if parsed.action == "new_session":
        metadata = _build_terminal_metadata(
            tty_path=tty_path,
            parent_pid=parent_pid,
            cols=cols,
            rows=rows,
            cwd=cwd,
        )
        payload = cast(TerminalOutboxPayload, {"session_id": "", "args": parsed.args})
        response = _dispatch_terminal_event(db_path, TeleClaudeEvents.NEW_SESSION, payload, metadata)
        if response is None or response.get("status") != "success":
            error = response.get("error", "unknown error") if response else "unknown error"
            sys.stderr.write(f"telec error: {error}\n")
            sys.exit(1)
        data = response.get("data")
        session_id = data.get("session_id") if isinstance(data, dict) else None
        if not session_id:
            sys.stderr.write("telec error: session creation failed\n")
            sys.exit(1)
        entry = _get_session_entry_by_id(db_path, str(session_id))
        if not entry:
            sys.stderr.write("telec error: session not found after creation\n")
            sys.exit(1)
        _attach_session_entry(entry)
        return

    if parsed.action == "start":
        agent_name = normalize_agent_name(parsed.agent or "")
        thinking_mode, user_args = _parse_agent_args(agent_name, parsed.args, None)
        description_args = user_args
        auto_command = shlex.join(["agent", agent_name, thinking_mode] + user_args)

        metadata = _build_terminal_metadata(
            tty_path=tty_path,
            parent_pid=parent_pid,
            cols=cols,
            rows=rows,
            cwd=cwd,
            auto_command=auto_command,
        )
        payload = cast(TerminalOutboxPayload, {"session_id": "", "args": description_args})
        response = _dispatch_terminal_event(db_path, TeleClaudeEvents.NEW_SESSION, payload, metadata)
        if response is None or response.get("status") != "success":
            error = response.get("error", "unknown error") if response else "unknown error"
            sys.stderr.write(f"telec error: {error}\n")
            sys.exit(1)
        data = response.get("data")
        session_id = data.get("session_id") if isinstance(data, dict) else None
        if not session_id:
            sys.stderr.write("telec error: session creation failed\n")
            sys.exit(1)
        entry = _get_session_entry_by_id(db_path, str(session_id))
        if not entry:
            sys.stderr.write("telec error: session not found after creation\n")
            sys.exit(1)
        _attach_session_entry(entry)
        return

    if parsed.action == "resume":
        entry: SessionListEntry | None = None
        if parsed.session_id:
            entry = _select_session_entry(db_path, parsed.session_id)
        else:
            session_id = _find_session_id_for_tty(db_path, tty_path)
            if session_id:
                entry = _get_session_entry_by_id(db_path, session_id)

        if entry:
            metadata = MessageMetadata(adapter_type="terminal")
            empty_args = list[str]()
            payload = cast(TerminalOutboxPayload, {"session_id": entry.session_id, "args": empty_args})
            _dispatch_terminal_event(
                db_path,
                TeleClaudeEvents.AGENT_RESUME,
                payload,
                metadata,
                wait_for_response=True,
            )
            _attach_session_entry(entry)
            return

        auto_command = "agent_resume"
        metadata = _build_terminal_metadata(
            tty_path=tty_path,
            parent_pid=parent_pid,
            cols=cols,
            rows=rows,
            cwd=cwd,
            auto_command=auto_command,
        )
        empty_args = list[str]()
        payload = cast(TerminalOutboxPayload, {"session_id": "", "args": empty_args})
        response = _dispatch_terminal_event(db_path, TeleClaudeEvents.NEW_SESSION, payload, metadata)
        if response is None or response.get("status") != "success":
            error = response.get("error", "unknown error") if response else "unknown error"
            sys.stderr.write(f"telec error: {error}\n")
            sys.exit(1)
        data = response.get("data")
        session_id = data.get("session_id") if isinstance(data, dict) else None
        if not session_id:
            sys.stderr.write("telec error: session creation failed\n")
            sys.exit(1)
        entry = _get_session_entry_by_id(db_path, str(session_id))
        if not entry:
            sys.stderr.write("telec error: session not found after creation\n")
            sys.exit(1)
        _attach_session_entry(entry)
        return

    sys.stderr.write("telec error: unsupported command\n")
    sys.exit(1)


def main() -> None:
    try:
        _main_impl()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
