"""telec: terminal CLI for starting TeleClaude agent sessions."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, TextIO, cast

from teleclaude.config import config
from teleclaude.core import terminal_bridge
from teleclaude.core.agents import get_agent_command, normalize_agent_name
from teleclaude.core.events import parse_command_string
from teleclaude.core.models import ThinkingMode
from teleclaude.core.session_utils import get_output_file, update_title_with_agent
from teleclaude.core.terminal_sessions import ensure_terminal_session, terminal_tmux_name_for_session
from teleclaude.core.ux_state import SessionUXState, UXStatePayload

_UNSET = object()


@dataclass
class TelecCommand:
    action: str  # "start" | "resume"
    agent: str | None
    args: list[str]
    session_id: str | None


@dataclass
class SessionRow:
    session_id: str
    title: str | None
    origin_adapter: str | None
    ux_state_raw: str | None


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
        "  telec ls                   # list sessions\n"
        "  telec attach <id|index>    # attach to tmux session\n"
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


def parse_telec_command(argv: list[str]) -> TelecCommand:
    if not argv:
        raise ValueError(_usage())

    command_str = " ".join(argv)
    cmd_name, args = parse_command_string(command_str)
    if not cmd_name:
        raise ValueError(_usage())

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


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


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
               working_directory, last_activity, created_at, ux_state
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
        ux_state_raw = row[7]
        ux_state = SessionUXState()
        if isinstance(ux_state_raw, str) and ux_state_raw:
            try:
                parsed_raw: object = json.loads(ux_state_raw)
                if isinstance(parsed_raw, dict):
                    ux_state = SessionUXState.from_dict(cast(UXStatePayload, parsed_raw))
            except Exception:
                ux_state = SessionUXState()
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
                active_agent=ux_state.active_agent if ux_state else None,
                thinking_mode=ux_state.thinking_mode if ux_state else None,
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
    header = f"{'Idx':>3}  {'ID':<8}  {'Agent':<6}  {'Mode':<4}  {'Last Active':<16}  {'Tmux':<4}  Title"
    print(header)
    print("-" * len(header))
    for entry in entries:
        agent = entry.active_agent or "—"
        mode = entry.thinking_mode or "—"
        last = _format_timestamp(entry.last_activity or entry.created_at)
        tmux = "yes" if entry.tmux_ready else "no"
        title = entry.title
        print(f"{entry.index:>3}  {entry.session_id[:8]:<8}  {agent:<6}  {mode:<4}  {last:<16}  {tmux:<4}  {title}")


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
        "- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -",
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
                "Idx  ID       Agent  Mode  Last Active        Tmux  Title"[:width],
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
                tmux = "yes" if entry.tmux_ready else "no"
                line = (
                    f"{entry.index:>3}  {entry.session_id[:8]:<8}  "
                    f"{(entry.active_agent or '—'):<6}  {(entry.thinking_mode or '—'):<4}  "
                    f"{last:<16}  {tmux:<4}  {entry.title}"
                )
                row_y = table_header_row + 2 + i
                if row_idx == selected:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addstr(row_y, 0, line[:width])
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addstr(row_y, 0, line[:width])

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


def _load_session(conn: sqlite3.Connection, session_id: str) -> SessionRow | None:
    cursor = conn.execute(
        "SELECT session_id, title, origin_adapter, ux_state FROM sessions WHERE session_id = ?",
        (session_id,),
    )
    row = cast(tuple[object, object, object, object] | None, cursor.fetchone())
    if not row:
        return None
    return SessionRow(
        session_id=str(row[0]),
        title=str(row[1]) if row[1] is not None else None,
        origin_adapter=str(row[2]) if row[2] is not None else None,
        ux_state_raw=str(row[3]) if row[3] is not None else None,
    )


def _load_ux_state(conn: sqlite3.Connection, session_id: str) -> SessionUXState:
    cursor = conn.execute("SELECT ux_state FROM sessions WHERE session_id = ?", (session_id,))
    row = cast(tuple[object, ...] | None, cursor.fetchone())
    if not row:
        return SessionUXState()
    if not row[0]:
        return SessionUXState()
    try:
        data = row[0]
        if isinstance(data, str):
            parsed_raw: object = json.loads(data)
            if isinstance(parsed_raw, dict):
                return SessionUXState.from_dict(cast(UXStatePayload, parsed_raw))
    except Exception:
        return SessionUXState()
    return SessionUXState()


def _update_ux_state(conn: sqlite3.Connection, session_id: str, **updates: object) -> None:
    cursor = conn.execute("SELECT ux_state FROM sessions WHERE session_id = ?", (session_id,))
    row = cast(tuple[object, ...] | None, cursor.fetchone())
    existing = {}
    if row and row[0]:
        try:
            if isinstance(row[0], str):
                existing_raw: object = json.loads(row[0])
                if isinstance(existing_raw, dict):
                    existing = existing_raw
        except Exception:
            existing = {}
    for key, value in updates.items():
        if value is _UNSET:
            continue
        existing[key] = value

    conn.execute(
        "UPDATE sessions SET ux_state = ?, last_activity = CURRENT_TIMESTAMP WHERE session_id = ?",
        (json.dumps(existing), session_id),
    )


def _build_agent_start_command(
    agent_name: str,
    args: list[str],
    stored_mode: str | None,
) -> tuple[str, str]:
    default_mode = stored_mode or ThinkingMode.SLOW.value
    thinking_mode, user_args = _split_thinking_mode(args, default_mode, agent_name)
    has_prompt = bool(user_args)

    base_cmd = get_agent_command(agent_name, thinking_mode=thinking_mode, interactive=has_prompt)
    if user_args:
        quoted = [shlex.quote(arg) for arg in user_args]
        base_cmd = f"{base_cmd} {' '.join(quoted)}"
    return base_cmd, thinking_mode


def _build_agent_resume_command(agent_name: str, ux_state: SessionUXState) -> str:
    thinking_mode = ux_state.thinking_mode or ThinkingMode.SLOW.value
    native_session_id = ux_state.native_session_id
    return get_agent_command(
        agent=agent_name,
        thinking_mode=thinking_mode,
        exec=False,
        resume=not native_session_id,
        native_session_id=native_session_id,
    )


def _prepare_resume_state(ux_state: SessionUXState, explicit_session_id: bool) -> SessionUXState:
    """Prefer 'resume latest' unless the user targets a specific TeleClaude session."""
    if explicit_session_id or not ux_state.native_session_id:
        return ux_state

    fresh = SessionUXState.from_dict(cast(UXStatePayload, ux_state.to_dict()))
    fresh.native_session_id = None
    return fresh


def _wrap_with_script(cmd: str, log_file: str | None) -> str:
    if not log_file:
        return cmd
    if not shutil.which("script"):
        return cmd
    # macOS script(1) doesn't support -c; pass command as args to /bin/sh for portability.
    return f"script -q {shlex.quote(log_file)} /bin/sh -c {shlex.quote(cmd)}"


def _terminal_size() -> tuple[int, int]:
    size = shutil.get_terminal_size((160, 80))
    return size.columns, size.lines


def _resolve_working_dir(value: str | None, fallback: str) -> str:
    candidates = [
        os.path.expanduser(value) if value else "",
        os.path.expanduser(fallback) if fallback else "",
        os.path.expanduser("~"),
        os.getcwd(),
    ]
    for candidate in candidates:
        if candidate and os.path.isdir(candidate):
            return candidate
    return os.getcwd()


def _ensure_tmux_session(
    *,
    session_name: str,
    session_id: str,
    working_dir: str,
    cols: int,
    rows: int,
    env_vars: dict[str, str],
) -> None:
    async def _run() -> None:
        if await terminal_bridge.session_exists(session_name, log_missing=False):
            ok = await terminal_bridge.update_tmux_session(session_name, env_vars)
            if not ok:
                raise RuntimeError(f"Failed to update tmux env for {session_name}")
            return
        ok = await terminal_bridge.create_tmux_session(
            name=session_name,
            working_dir=working_dir,
            cols=cols,
            rows=rows,
            session_id=session_id,
            env_vars=env_vars,
        )
        if not ok:
            raise RuntimeError(f"Failed to create tmux session {session_name}")

    asyncio.run(_run())


def _update_tmux_tty(db_path: str, session_id: str, session_name: str) -> None:
    async def _run() -> str | None:
        return await terminal_bridge.get_pane_tty(session_name)

    tmux_tty = asyncio.run(_run())
    if not tmux_tty:
        return

    conn = sqlite3.connect(db_path, timeout=1.0)
    try:
        conn.execute("PRAGMA busy_timeout = 1000")
        cursor = conn.execute("SELECT ux_state FROM sessions WHERE session_id = ?", (session_id,))
        row = cast(tuple[object] | None, cursor.fetchone())
        existing: dict[str, object] = {}  # noqa: loose-dict - UX state JSON blob
        if row and row[0]:
            try:
                if isinstance(row[0], str):
                    parsed_raw: object = json.loads(row[0])
                    if isinstance(parsed_raw, dict):
                        existing = parsed_raw
            except Exception:
                existing = {}
        if existing.get("tmux_tty_path") == tmux_tty:
            return
        existing["tmux_tty_path"] = tmux_tty
        conn.execute(
            "UPDATE sessions SET ux_state = ? WHERE session_id = ?",
            (json.dumps(existing), session_id),
        )
        conn.commit()
    finally:
        conn.close()


def _send_tmux_command(session_name: str, cmd: str, agent_name: str | None) -> None:
    async def _run() -> None:
        ok = await terminal_bridge.send_keys_existing_tmux(
            session_name=session_name,
            text=cmd,
            send_enter=True,
            active_agent=agent_name,
        )
        if not ok:
            raise RuntimeError(f"Failed to send command to tmux session {session_name}")

    asyncio.run(_run())


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


def _attach_session_entry(
    *,
    db_path: str,
    entry: SessionListEntry,
    tty_path: str,
    parent_pid: int,
    cwd: str,
) -> None:
    session_id = entry.session_id
    tmux_name = _resolve_tmux_name(entry)

    conn = sqlite3.connect(db_path, timeout=1.0)
    try:
        conn.execute("PRAGMA busy_timeout = 1000")
        if tmux_name != entry.tmux_session_name:
            conn.execute(
                "UPDATE sessions SET tmux_session_name = ? WHERE session_id = ?",
                (tmux_name, session_id),
            )
        _update_ux_state(
            conn,
            session_id,
            native_tty_path=tty_path,
            native_pid=parent_pid if parent_pid > 1 else None,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if not shutil.which("tmux"):
        raise ValueError("tmux is required for terminal sessions")

    cols, rows = _terminal_size()
    env_vars = {
        "TELECLAUDE_SESSION_ID": session_id,
        "TELECLAUDE_TTY": tty_path,
    }
    if parent_pid > 1:
        env_vars["TELECLAUDE_PID"] = str(parent_pid)

    working_dir = _resolve_working_dir(entry.working_directory, cwd)
    if entry.working_directory != working_dir:
        conn = sqlite3.connect(db_path, timeout=1.0)
        try:
            conn.execute("PRAGMA busy_timeout = 1000")
            conn.execute(
                "UPDATE sessions SET working_directory = ? WHERE session_id = ?",
                (working_dir, session_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            conn.close()
    _ensure_tmux_session(
        session_name=tmux_name,
        session_id=session_id,
        working_dir=working_dir,
        cols=cols,
        rows=rows,
        env_vars=env_vars,
    )
    _update_tmux_tty(db_path, session_id, tmux_name)

    _attach_tmux(tmux_name)


def main() -> None:
    argv = sys.argv[1:]
    db_path = config.database.path

    if argv and argv[0] in {"ls", "list", "sessions"}:
        _list_sessions(db_path)
        return

    if not argv or argv[0] in {"attach", "open"}:
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

        tty_path = _resolve_tty()
        if not tty_path:
            sys.stderr.write("telec: could not resolve a controlling TTY\n")
            sys.exit(1)

        parent_pid = os.getppid()
        cwd = os.getcwd()

        try:
            _attach_session_entry(
                db_path=db_path,
                entry=entry,
                tty_path=tty_path,
                parent_pid=parent_pid,
                cwd=cwd,
            )
        except ValueError as exc:
            sys.stderr.write(f"telec error: {exc}\n")
            sys.exit(1)
        return

    try:
        parsed = parse_telec_command(argv)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(1)

    tty_path = _resolve_tty()
    if not tty_path:
        sys.stderr.write("telec: could not resolve a controlling TTY\n")
        sys.exit(1)

    parent_pid = os.getppid()
    cwd = os.getcwd()

    session_id: str | None = None
    agent_name: str | None = None
    tmux_name: str | None = None
    cmd: str | None = None

    conn = sqlite3.connect(db_path, timeout=1.0)
    try:
        conn.execute("PRAGMA busy_timeout = 1000")

        if parsed.action == "start":
            agent_name = normalize_agent_name(parsed.agent or "")
            session_id = ensure_terminal_session(tty_path, parent_pid, agent_name, cwd)
        elif parsed.session_id:
            session = _load_session(conn, parsed.session_id)
            if not session:
                raise ValueError(f"Session {parsed.session_id[:8]} not found")
            if session.origin_adapter != "terminal":
                raise ValueError("telec can only resume terminal-origin sessions")
            session_id = parsed.session_id
        else:
            session_id = ensure_terminal_session(tty_path, parent_pid, None, cwd)

        if not session_id:
            raise ValueError("Failed to resolve TeleClaude session")

        tmux_name = terminal_tmux_name_for_session(session_id)
        conn.execute("UPDATE sessions SET tmux_session_name = ? WHERE session_id = ?", (tmux_name, session_id))

        ux_state = _load_ux_state(conn, session_id)

        if parsed.action == "start":
            if not agent_name:
                agent_name = normalize_agent_name(parsed.agent or "")
            cmd, thinking_mode = _build_agent_start_command(agent_name, parsed.args, ux_state.thinking_mode)
            log_file = ux_state.tui_log_file or str(get_output_file(session_id))
            cmd = _wrap_with_script(cmd, log_file)

            _update_ux_state(
                conn,
                session_id,
                active_agent=agent_name,
                thinking_mode=thinking_mode,
                native_session_id=None,
                native_log_file=None,
                tui_log_file=log_file,
                tui_capture_started=True,
                native_tty_path=tty_path,
                native_pid=parent_pid if parent_pid > 1 else None,
            )

            title_row = _load_session(conn, session_id)
            if title_row and title_row.title:
                new_title = update_title_with_agent(
                    title_row.title,
                    agent_name,
                    thinking_mode,
                    config.computer.name,
                )
                if new_title:
                    conn.execute("UPDATE sessions SET title = ? WHERE session_id = ?", (new_title, session_id))

        else:
            if parsed.session_id:
                _update_ux_state(
                    conn,
                    session_id,
                    native_tty_path=tty_path,
                    native_pid=parent_pid if parent_pid > 1 else None,
                )

            agent_name = ux_state.active_agent or parsed.agent
            if not agent_name:
                sys.stderr.write(f"Registered terminal session {session_id}\n")
            else:
                agent_name = normalize_agent_name(agent_name)
                resume_state = _prepare_resume_state(ux_state, explicit_session_id=bool(parsed.session_id))
                cmd = _build_agent_resume_command(agent_name, resume_state)
                log_file = ux_state.tui_log_file or str(get_output_file(session_id))
                cmd = _wrap_with_script(cmd, log_file)
                _update_ux_state(
                    conn,
                    session_id,
                    active_agent=agent_name,
                    tui_log_file=log_file,
                    tui_capture_started=True,
                )

        conn.commit()
    except Exception as exc:
        conn.rollback()
        sys.stderr.write(f"telec error: {exc}\n")
        sys.exit(1)
    finally:
        conn.close()

    if not tmux_name:
        sys.stderr.write("telec error: failed to resolve tmux session name\n")
        sys.exit(1)

    if not shutil.which("tmux"):
        sys.stderr.write("telec error: tmux is required for terminal sessions\n")
        sys.exit(1)

    cols, rows = _terminal_size()
    env_vars = {
        "TELECLAUDE_SESSION_ID": session_id,
        "TELECLAUDE_TTY": tty_path,
    }
    if parent_pid > 1:
        env_vars["TELECLAUDE_PID"] = str(parent_pid)

    _ensure_tmux_session(
        session_name=tmux_name,
        session_id=session_id,
        working_dir=cwd,
        cols=cols,
        rows=rows,
        env_vars=env_vars,
    )
    _update_tmux_tty(db_path, session_id, tmux_name)

    if cmd:
        _send_tmux_command(tmux_name, cmd, agent_name)

    _attach_tmux(tmux_name)


if __name__ == "__main__":
    main()
