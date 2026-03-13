"""Tmux key-sending functions: text input, signals, and special keys."""

import asyncio
import errno
import fcntl
import os
import termios
import time
from pathlib import Path
from signal import SIGINT, SIGKILL, SIGTERM, Signals

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.agents import AgentName

from ._session import ensure_tmux_session
from ._subprocess import SUBPROCESS_TIMEOUT_QUICK, communicate_with_timeout, wait_with_timeout

logger = get_logger(__name__)


def pid_is_alive(pid: int) -> bool:
    """Return True if a PID appears to be alive."""
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


async def send_keys(
    session_name: str,
    text: str,
    session_id: str | None = None,
    working_dir: str = "~",
    send_enter: bool = True,
    active_agent: str | None = None,
) -> bool:
    """Send keys (text) to a tmux session, creating a new session if needed.

    If the session doesn't exist (crashed or never created), creates a fresh
    session with the same name. Previous state is lost - this is NOT recovery,
    just creating a new session so the user can continue working.

    Args:
        session_name: Session name
        text: Text to send
        session_id: TeleClaude session ID (used for env var + TMPDIR injection on tmux recreation)
        working_dir: Working directory if creating new session (default: ~)
        send_enter: If True, send Enter key after text. Set to False for arrow keys. (default: True)
        active_agent: Active agent name (e.g., "gemini") for agent-specific escaping

    Returns:
        bool: True if command sent successfully, False on failure
    """
    try:
        # Check if session exists, create if not
        if not await ensure_tmux_session(
            name=session_name,
            working_dir=working_dir,
            session_id=session_id,
        ):
            logger.error("Failed to ensure session %s", session_name)
            return False

        return await _send_keys_tmux(
            session_name=session_name,
            text=text,
            send_enter=send_enter,
            active_agent=active_agent,
        )

    except Exception as e:
        logger.exception("Error sending keys to tmux session %s: %s", session_name, e)
        return False


async def send_keys_existing_tmux(
    session_name: str,
    text: str,
    *,
    send_enter: bool = True,
    active_agent: str | None = None,
) -> bool:
    """Send keys to an existing tmux session (do not auto-create).

    Callers are expected to have verified session existence before calling this function
    (e.g. tmux_io._send_to_tmux checks session_exists before dispatching here).
    The redundant double-check is intentionally removed to avoid an extra subprocess call.
    """
    try:
        return await _send_keys_tmux(
            session_name=session_name,
            text=text,
            send_enter=send_enter,
            active_agent=active_agent,
        )
    except Exception as e:
        logger.exception("Error sending keys to existing tmux session %s: %s", session_name, e)
        return False


async def send_keys_to_tty(tty_path: str, text: str, *, send_enter: bool = True) -> bool:
    """Send keys directly to a controlling TTY (non-tmux sessions)."""
    try:
        payload = text + ("\n" if send_enter else "")
        data = payload.encode()

        def _is_pty_master(path: str) -> bool:
            name = Path(path).name
            return name.startswith(("pty", "ptys", "ptyp"))

        def _inject() -> None:
            fd = os.open(tty_path, os.O_RDWR | os.O_NOCTTY)
            try:
                if _is_pty_master(tty_path):
                    _write_fallback(fd, data)
                    return
                if not hasattr(termios, "TIOCSTI"):
                    raise OSError("TIOCSTI unavailable for TTY injection")

                deadline = time.monotonic() + 5.0
                for byte in data:
                    while True:
                        try:
                            fcntl.ioctl(fd, termios.TIOCSTI, bytes([byte]))
                            break
                        except OSError as exc:
                            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR, errno.ENOMEM):
                                if time.monotonic() >= deadline:
                                    raise OSError("TIOCSTI timeout") from exc
                                time.sleep(0.01)
                                continue
                            raise
            finally:
                os.close(fd)

        def _write_fallback(fd: int, buffer: bytes) -> None:
            total = 0
            while total < len(buffer):
                written = os.write(fd, buffer[total:])
                if written <= 0:
                    break
                total += written

        await asyncio.to_thread(_inject)
        return True
    except Exception as e:
        logger.exception("Error sending keys to tty %s: %s", tty_path, e)
        return False


async def _send_keys_tmux(
    *,
    session_name: str,
    text: str,
    send_enter: bool,
    active_agent: str | None,
) -> bool:
    """Send keys to tmux (session must already exist)."""
    # Gemini CLI can't handle '!' character - escape it
    # See: https://github.com/google-gemini/gemini-cli/issues/4454
    send_text = text.replace("!", r"\!") if active_agent == AgentName.GEMINI.value else text

    # Check if text contains bracketed paste markers
    has_bracketed_paste = "\x1b[200~" in send_text or "\x1b[201~" in send_text
    if has_bracketed_paste:
        # tmux send-keys without -l can fail with "not in a mode" when ESC sequences
        # are present. Unwrap markers and always send text via literal mode.
        send_text = send_text.replace("\x1b[200~", "").replace("\x1b[201~", "")

    # Send command (no pipes - don't leak file descriptors)
    # UPDATE: We must capture stderr to debug failures. send-keys is ephemeral and doesn't
    # start a long-lived process that would inherit the pipe, so this is safe.
    # Always send with -l for literal interpretation (prevents shell/key-name expansion).
    cmd_text = [config.computer.tmux_binary, "send-keys", "-t", session_name, "-l", "--", send_text]
    if has_bracketed_paste:
        logger.debug("Unwrapped bracketed paste markers for literal tmux send: %s", send_text[:80])
    result = await asyncio.create_subprocess_exec(
        *cmd_text, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

    if result.returncode != 0:
        logger.error(
            "Failed to send text to session %s: returncode=%d, stderr=%s",
            session_name,
            result.returncode,
            stderr.decode().strip(),
        )
        return False

    # Small delay to ensure text is buffered by tmux before we send Enter.
    # Investigation: Reducing to 0.1s causes test flakiness and missed Enter key delivery on
    # slow hosts. 1.0s is conservative but keeps the path reliable. The inbound queue
    # now bears the latency cost; adapter responsiveness is unaffected.
    await asyncio.sleep(1.0)

    # Send Enter key once if requested
    if send_enter:
        cmd_enter = [config.computer.tmux_binary, "send-keys", "-t", session_name, "C-m"]
        result = await asyncio.create_subprocess_exec(
            *cmd_enter, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode != 0:
            logger.error(
                "Failed to send Enter to session %s: returncode=%d, stderr=%s",
                session_name,
                result.returncode,
                stderr.decode().strip(),
            )
            return False

    return True


async def send_signal(session_name: str, signal: Signals = SIGINT) -> bool:
    """Send signal to a tmux session.

    Args:
        session_name: Session name
        signal: Signal name (SIGINT, SIGTERM, SIGKILL)

    Returns:
        True if successful, False otherwise
    """
    try:
        if signal is SIGKILL:
            # SIGKILL requires finding the process PID and killing it directly
            # Get the shell PID in the tmux pane
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
                return False

            shell_pid = stdout.decode().strip()
            if not shell_pid.isdigit():
                logger.error("Invalid shell PID: %s", shell_pid)
                return False

            # Find child processes of the shell (the actual running command)
            # Use pgrep to find all descendant processes
            cmd = ["pgrep", "-P", shell_pid]
            result = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

            if result.returncode != 0 or not stdout:
                logger.warning(
                    "No child processes found for shell PID %s in session %s",
                    shell_pid,
                    session_name,
                )
                return False

            # Get the first child PID (foreground process)
            child_pids = stdout.decode().strip().split("\n")
            target_pid = child_pids[0].strip()

            if not target_pid.isdigit():
                logger.error("Invalid child PID: %s", target_pid)
                return False

            # Send SIGKILL to the foreground process
            cmd = ["kill", "-9", target_pid]
            result = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

            if result.returncode != 0:
                logger.error(
                    "Failed to send SIGKILL to PID %s: %s",
                    target_pid,
                    stderr.decode().strip(),
                )
                return False

            logger.info("Sent SIGKILL to PID %s in session %s", target_pid, session_name)
            return True

        # Handle SIGINT and SIGTERM via tmux send-keys
        if signal is SIGINT:
            key = "C-c"
        elif signal is SIGTERM:
            key = "C-\\"
        else:
            logger.error("Unsupported signal: %s", signal)
            return False

        cmd = [config.computer.tmux_binary, "send-keys", "-t", session_name, key]
        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode != 0:
            logger.error(
                "Failed to send signal %s to tmux session %s (exit %d): %s",
                signal,
                session_name,
                result.returncode,
                stderr.decode().strip(),
            )
            return False

        return True

    except Exception as e:
        logger.error("Exception sending signal %s to tmux session %s: %s", signal, session_name, e)
        return False


async def send_escape(session_name: str) -> bool:
    """Send ESCAPE key to a tmux session.

    Args:
        session_name: Session name

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = [config.computer.tmux_binary, "send-keys", "-t", session_name, "Escape"]
        result = await asyncio.create_subprocess_exec(*cmd)
        await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        return result.returncode == 0

    except Exception as e:
        print(f"Error sending escape to tmux: {e}")
        return False


async def send_ctrl_key(session_name: str, key: str) -> bool:
    """Send CTRL+key combination to a tmux session.

    Args:
        session_name: Session name
        key: Key to send with CTRL modifier (e.g., 'c', 'd', 'z')

    Returns:
        True if successful, False otherwise
    """
    try:
        # tmux notation for control keys: C-<key>
        ctrl_key = f"C-{key.lower()}"
        cmd = [config.computer.tmux_binary, "send-keys", "-t", session_name, ctrl_key]
        result = await asyncio.create_subprocess_exec(*cmd)
        await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        return result.returncode == 0

    except Exception as e:
        print(f"Error sending ctrl+{key} to tmux: {e}")
        return False


async def send_tab(session_name: str) -> bool:
    """Send TAB key to a tmux session.

    Args:
        session_name: Session name

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = [config.computer.tmux_binary, "send-keys", "-t", session_name, "Tab"]
        result = await asyncio.create_subprocess_exec(*cmd)
        await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        return result.returncode == 0

    except Exception as e:
        print(f"Error sending tab to tmux: {e}")
        return False


async def send_shift_tab(session_name: str, count: int = 1) -> bool:
    """Send SHIFT+TAB (backtab) key to a tmux session, optionally repeated.

    Args:
        session_name: Session name
        count: Number of times to repeat the key (default: 1)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Validate count
        if count < 1:
            logger.error("Invalid count: %s (must be >= 1)", count)
            return False

        # tmux send-keys with -N flag for repeat count
        cmd = [config.computer.tmux_binary, "send-keys", "-t", session_name, "-N", str(count), "BTab"]
        result = await asyncio.create_subprocess_exec(*cmd)
        await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        return result.returncode == 0

    except Exception as e:
        print(f"Error sending shift+tab (x{count}) to tmux: {e}")
        return False


async def send_backspace(session_name: str, count: int = 1) -> bool:
    """Send BACKSPACE key to a tmux session, optionally repeated.

    Args:
        session_name: Session name
        count: Number of times to repeat the key (default: 1)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Validate count
        if count < 1:
            logger.error("Invalid count: %s (must be >= 1)", count)
            return False

        # tmux send-keys with -N flag for repeat count
        cmd = [config.computer.tmux_binary, "send-keys", "-t", session_name, "-N", str(count), "BSpace"]
        result = await asyncio.create_subprocess_exec(*cmd)
        await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        return result.returncode == 0

    except Exception as e:
        print(f"Error sending backspace (x{count}) to tmux: {e}")
        return False


async def send_enter(session_name: str) -> bool:
    """Send ENTER key to a tmux session.

    Args:
        session_name: Session name

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = [config.computer.tmux_binary, "send-keys", "-t", session_name, "C-m"]
        result = await asyncio.create_subprocess_exec(*cmd)
        await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        return result.returncode == 0

    except Exception as e:
        print(f"Error sending enter to tmux: {e}")
        return False


async def send_arrow_key(session_name: str, direction: str, count: int = 1) -> bool:
    """Send arrow key to a tmux session, optionally repeated.

    Args:
        session_name: Session name
        direction: Arrow direction ('up', 'down', 'left', 'right')
        count: Number of times to repeat the key (default: 1)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Validate direction
        valid_directions = {"up": "Up", "down": "Down", "left": "Left", "right": "Right"}
        if direction not in valid_directions:
            logger.error("Invalid arrow direction: %s", direction)
            return False

        # Validate count
        if count < 1:
            logger.error("Invalid count: %s (must be >= 1)", count)
            return False

        # tmux send-keys with -N flag for repeat count
        key_name = valid_directions[direction]
        cmd = [config.computer.tmux_binary, "send-keys", "-t", session_name, "-N", str(count), key_name]
        result = await asyncio.create_subprocess_exec(*cmd)
        await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        return result.returncode == 0

    except Exception as e:
        print(f"Error sending arrow key ({direction} x{count}) to tmux: {e}")
        return False
