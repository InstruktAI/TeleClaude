"""Tmux pane operations: capture, query, pipe, and process state."""

import asyncio
import os
import pwd
import time
from pathlib import Path

import psutil
from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import UI_MESSAGE_MAX_CHARS

from ._subprocess import (
    SUBPROCESS_TIMEOUT_QUICK,
    SubprocessTimeoutError,
    communicate_with_timeout,
    wait_with_timeout,
)

logger = get_logger(__name__)

# User's shell basename, computed once at import
# Used for shell readiness detection in is_process_running()/wait_for_shell_ready()
_SHELL_NAME = Path(os.environ.get("SHELL") or pwd.getpwuid(os.getuid()).pw_shell).name.lower()


async def get_pane_tty(session_name: str) -> str | None:
    """Get tty path for the tmux pane backing a session."""
    try:
        cmd = [config.computer.tmux_binary, "display-message", "-p", "-t", session_name, "#{pane_tty}"]
        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")
        if result.returncode != 0:
            logger.error(
                "Failed to get pane tty for session %s: %s",
                session_name,
                stderr.decode().strip(),
            )
            return None

        tty = stdout.decode().strip()
        if not tty or tty in {"?", "??"}:
            return None
        return tty
    except Exception as e:
        logger.error("Exception getting pane tty for %s: %s", session_name, e)
        return None


async def get_pane_pid(session_name: str) -> int | None:
    """Get shell PID for the tmux pane backing a session."""
    try:
        cmd = [config.computer.tmux_binary, "display-message", "-p", "-t", session_name, "#{pane_pid}"]
        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")
        if result.returncode != 0:
            logger.error(
                "Failed to get pane PID for session %s: %s",
                session_name,
                stderr.decode().strip(),
            )
            return None

        pid_str = stdout.decode().strip()
        if not pid_str.isdigit():
            return None
        return int(pid_str)
    except Exception as e:
        logger.error("Exception getting pane PID for %s: %s", session_name, e)
        return None


async def capture_pane(session_name: str, *, capture_lines: int | None = None) -> str:
    """Capture pane output from tmux session.

    Args:
        session_name: Session name

    Returns:
        Captured output as string
    """
    try:
        # -p = print to stdout
        # -S -N = capture from the last N lines of scrollback.
        # -J = preserve trailing spaces (better for capturing exact output)
        # -e = include escape sequences (ANSI codes for styling detection)
        window_lines = capture_lines if isinstance(capture_lines, int) and capture_lines > 0 else UI_MESSAGE_MAX_CHARS
        cmd = [
            config.computer.tmux_binary,
            "capture-pane",
            "-t",
            session_name,
            "-p",
            "-J",
            "-e",
            "-S",
            f"-{window_lines}",
        ]

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode == 0:
            return stdout.decode("utf-8", errors="replace")

        logger.warning(
            "Failed to capture pane from session %s: returncode=%d, stderr=%s",
            session_name,
            result.returncode,
            stderr.decode().strip(),
        )
        return ""

    except SubprocessTimeoutError as e:
        logger.error("Timeout capturing pane from session %s: %s", session_name, e)
        raise
    except Exception as e:
        logger.error("Exception capturing pane from session %s: %s", session_name, e)
        raise


async def kill_session(session_name: str) -> bool:
    """Kill a tmux session.

    Args:
        session_name: Session name

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = [config.computer.tmux_binary, "kill-session", "-t", session_name]
        result = await asyncio.create_subprocess_exec(*cmd)
        await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        return result.returncode == 0

    except Exception as e:
        print(f"Error killing session: {e}")
        return False


async def list_tmux_sessions() -> list[str]:
    """List all tmux sessions.

    Returns:
        List of session names
    """
    try:
        cmd = [config.computer.tmux_binary, "list-sessions", "-F", "#{session_name}"]

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode == 0:
            sessions: list[str] = stdout.decode("utf-8").strip().split("\n")
            return [s for s in sessions if s]  # Filter empty strings
        return []

    except Exception as e:
        print(f"Error listing sessions: {e}")
        return []


async def session_exists(session_name: str, log_missing: bool = True) -> bool:
    """Check if a tmux session exists.

    Args:
        session_name: Session name
        log_missing: If True, log ERROR with diagnostics when session is missing.
                     Set to False when checking expected-terminated sessions to avoid noise.

    Returns:
        True if session exists, False otherwise
    """
    try:
        cmd = [config.computer.tmux_binary, "has-session", "-t", session_name]

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode != 0:
            if log_missing:
                # Session died - capture system state for diagnostics
                try:
                    # Get all tmux sessions
                    tmux_list_result = await asyncio.create_subprocess_exec(
                        config.computer.tmux_binary,
                        "list-sessions",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    tmux_list_stdout, _ = await communicate_with_timeout(
                        tmux_list_result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation"
                    )
                    tmux_sessions = tmux_list_stdout.decode().strip().split("\n") if tmux_list_stdout else []

                    # Get tmux processes and system metrics off the event loop to avoid blocking
                    def _collect_psutil_diag() -> tuple[list[object], object, object]:
                        procs: list[object] = [  # type: ignore[misc]
                            {"pid": p.pid, "create_time": p.create_time()}
                            for p in psutil.process_iter(["pid", "name", "create_time"])  # type: ignore[misc]
                            if Path(config.computer.tmux_binary).name.lower() in p.info["name"].lower()  # type: ignore[misc]
                        ]
                        mem = psutil.virtual_memory()  # type: ignore[misc]
                        cpu = psutil.cpu_percent(interval=0.1)  # type: ignore[misc]
                        return procs, mem, cpu

                    tmux_processes, memory, cpu_percent = await asyncio.to_thread(_collect_psutil_diag)  # type: ignore[misc]

                    logger.error(
                        "Session %s does not exist (died unexpectedly)",
                        session_name,
                        extra={
                            "session_name": session_name,
                            "stderr": stderr.decode().strip(),
                            "tmux_sessions_count": len([s for s in tmux_sessions if s]),
                            "tmux_processes_count": len(tmux_processes),  # type: ignore[misc]
                            "system_memory_used_mb": memory.used // 1024 // 1024,  # type: ignore[misc, attr-defined]
                            "system_memory_percent": memory.percent,  # type: ignore[misc, attr-defined]
                            "system_cpu_percent": cpu_percent,
                        },
                    )
                except Exception as diag_error:
                    logger.warning("Failed to capture diagnostics: %s", diag_error)

        return result.returncode == 0

    except SubprocessTimeoutError as e:
        logger.error("Timeout in session_exists for %s: %s", session_name, e)
        raise
    except Exception as e:
        logger.error("Exception in session_exists for %s: %s", session_name, e)
        raise


async def get_current_command(session_name: str) -> str | None:
    """Get the current foreground command running in a tmux pane.

    Uses tmux's #{pane_current_command} variable to detect interactive apps.

    Args:
        session_name: Session name

    Returns:
        Command name (e.g., "zsh", "claude", "vim") or None if detection failed
    """
    try:
        cmd = [config.computer.tmux_binary, "display-message", "-p", "-t", session_name, "#{pane_current_command}"]

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode != 0:
            logger.warning(
                "Failed to get current command for %s: returncode=%d, stderr=%s",
                session_name,
                result.returncode,
                stderr.decode().strip(),
            )
            return None

        command: str = stdout.decode().strip()
        return command

    except Exception as e:
        logger.error("Exception in get_current_command for %s: %s", session_name, e)
        return None


async def wait_for_shell_ready(
    session_name: str,
    timeout_s: float = 8.0,
    poll_interval_s: float = 0.2,
) -> bool:
    """Wait until the tmux pane returns to the user's shell.

    Returns True when the shell is in the foreground, False on timeout.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        current = await get_current_command(session_name)
        if current and current.lower() == _SHELL_NAME:
            return True
        await asyncio.sleep(poll_interval_s)
    return False


async def is_process_running(session_name: str) -> bool:
    """Return True if tmux foreground command is not the user's shell."""
    current = await get_current_command(session_name)
    if not current:
        return False
    return current.lower() != _SHELL_NAME


async def is_pane_dead(session_name: str) -> bool:
    """Return True if all tmux panes are marked dead (shell exited)."""
    try:
        cmd = [config.computer.tmux_binary, "list-panes", "-t", session_name, "-F", "#{pane_dead}"]
        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")
        if result.returncode != 0:
            return False
        lines = stdout.decode("utf-8").strip().split("\n") if stdout else []
        panes = [line.strip() for line in lines if line.strip()]
        if not panes:
            return False
        return all(int(pane) == 1 for pane in panes if pane.isdigit())
    except SubprocessTimeoutError as e:
        logger.error("Timeout checking pane_dead for %s: %s", session_name, e)
        raise
    except Exception as e:
        logger.error("Exception checking pane_dead for %s: %s", session_name, e)
        raise


async def get_session_pane_id(session_name: str) -> str | None:
    """Get the pane ID for a session (for pipe-pane).

    Args:
        session_name: Session name

    Returns:
        Pane ID or None
    """
    try:
        cmd = [config.computer.tmux_binary, "list-panes", "-t", session_name, "-F", "#{pane_id}"]

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode == 0:
            pane_id: str = stdout.decode("utf-8").strip()
            return pane_id if pane_id else None
        return None

    except Exception as e:
        print(f"Error getting pane ID: {e}")
        return None


async def start_pipe_pane(session_name: str, command: str) -> bool:
    """Start piping pane output to a command.

    Args:
        session_name: Session name
        command: Command to pipe output to

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = [config.computer.tmux_binary, "pipe-pane", "-t", session_name, "-o", command]
        result = await asyncio.create_subprocess_exec(*cmd)
        await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        return result.returncode == 0

    except Exception as e:
        print(f"Error starting pipe-pane: {e}")
        return False


async def stop_pipe_pane(session_name: str) -> bool:
    """Stop piping pane output.

    Args:
        session_name: Session name

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = [config.computer.tmux_binary, "pipe-pane", "-t", session_name]
        result = await asyncio.create_subprocess_exec(*cmd)
        await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        return result.returncode == 0

    except Exception as e:
        print(f"Error stopping pipe-pane: {e}")
        return False


async def get_pane_title(session_name: str) -> str | None:
    """Get the pane title for a tmux session.

    Args:
        session_name: Session name

    Returns:
        Pane title string or None if failed
    """
    try:
        cmd = [config.computer.tmux_binary, "display-message", "-p", "-t", session_name, "#{pane_title}"]
        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode == 0:
            pane_title: str = stdout.decode().strip()
            return pane_title

        return None

    except Exception as e:
        logger.error("Failed to get pane title for %s: %s", session_name, e)
        return None


async def get_current_directory(session_name: str) -> str | None:
    """Get the current working directory for a tmux session.

    Args:
        session_name: Session name

    Returns:
        Current directory path or None if failed
    """
    try:
        cmd = [config.computer.tmux_binary, "display", "-p", "-t", session_name, "#{pane_current_path}"]
        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode == 0:
            current_dir: str = stdout.decode().strip()
            return current_dir

        logger.warning(
            "Failed to get current directory for %s: returncode=%d, stderr=%s",
            session_name,
            result.returncode,
            stderr.decode().strip(),
        )
        return None

    except Exception as e:
        logger.error("Exception in get_current_directory for %s: %s", session_name, e)
        return None
