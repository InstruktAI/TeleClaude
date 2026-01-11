"""Terminal bridge for TeleClaude - handles tmux session management.

All functions are stateless and use config imported from teleclaude.config.
"""

import asyncio
import errno
import fcntl
import hashlib
import os
import pwd
import re
import shutil
import termios
import time
from pathlib import Path
from typing import Dict, List, Optional

import psutil
from instrukt_ai_logging import get_logger

from teleclaude.config import config

logger = get_logger(__name__)

# Subprocess timeout constants
SUBPROCESS_TIMEOUT_DEFAULT = 30.0  # Default timeout for subprocess operations
SUBPROCESS_TIMEOUT_QUICK = 5.0  # Timeout for quick operations (list, status checks)
SUBPROCESS_TIMEOUT_LONG = 60.0  # Timeout for long operations (complex commands)


class SubprocessTimeoutError(Exception):
    """Raised when a subprocess operation exceeds its timeout."""


async def wait_with_timeout(
    process: asyncio.subprocess.Process,
    timeout: float = SUBPROCESS_TIMEOUT_DEFAULT,
    operation: str = "subprocess",
) -> None:
    """
    Wait for a subprocess to complete with a timeout.

    If the timeout is exceeded, the process is killed and a SubprocessTimeoutError
    is raised. This prevents indefinite blocking if a subprocess hangs.

    Args:
        process: The subprocess to wait for
        timeout: Maximum time to wait in seconds
        operation: Description of the operation for error messages

    Raises:
        SubprocessTimeoutError: If the process doesn't complete within timeout
    """
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(
            "%s timeout after %.1fs, killing process %d",
            operation,
            timeout,
            process.pid if process.pid else -1,
        )
        try:
            process.kill()
            await wait_with_timeout(process, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")  # Clean up zombie
        except ProcessLookupError:
            pass  # Process already terminated
        raise SubprocessTimeoutError(f"{operation} timed out after {timeout}s")


async def communicate_with_timeout(
    process: asyncio.subprocess.Process,
    input_data: bytes | None = None,
    timeout: float = SUBPROCESS_TIMEOUT_DEFAULT,
    operation: str = "subprocess",
) -> tuple[bytes, bytes]:
    """
    Communicate with a subprocess with a timeout.

    If the timeout is exceeded, the process is killed and a SubprocessTimeoutError
    is raised. This prevents indefinite blocking if a subprocess hangs.

    Args:
        process: The subprocess to communicate with
        input_data: Optional input to send to the process
        timeout: Maximum time to wait in seconds
        operation: Description of the operation for error messages

    Returns:
        Tuple of (stdout, stderr) as bytes

    Raises:
        SubprocessTimeoutError: If communication doesn't complete within timeout
    """
    try:
        return await asyncio.wait_for(process.communicate(input_data), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(
            "%s timeout after %.1fs, killing process %d",
            operation,
            timeout,
            process.pid if process.pid else -1,
        )
        try:
            process.kill()
            await wait_with_timeout(process, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")  # Clean up zombie
        except ProcessLookupError:
            pass  # Process already terminated
        raise SubprocessTimeoutError(f"{operation} timed out after {timeout}s")


# User's shell basename, computed once at import
# Used for shell readiness detection in is_process_running()/wait_for_shell_ready()
_SHELL_NAME = Path(os.environ.get("SHELL") or pwd.getpwuid(os.getuid()).pw_shell).name.lower()


def _get_session_tmp_basedir() -> Path:
    override = os.environ.get("TELECLAUDE_SESSION_TMPDIR_BASE")
    if override:
        return Path(override).expanduser()
    return Path(os.path.expanduser("~/.teleclaude/tmp/sessions"))


def _safe_path_component(value: str) -> str:
    """Return a filesystem-safe path component derived from value."""
    if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value):
        return value
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _prepare_session_tmp_dir(session_id: str) -> Path:
    """Create an empty per-session temp directory.

    Claude Code (and other tools) may attempt to fs.watch() everything under TMPDIR.
    If TMPDIR contains unix sockets (e.g. docker_cli_*), Node-based watchers can crash.
    Using a dedicated, freshly created TMPDIR per tmux session avoids stray sockets.
    """
    safe_id = _safe_path_component(session_id)
    base_dir = _get_session_tmp_basedir()
    session_tmp = base_dir / safe_id

    base_dir.mkdir(parents=True, exist_ok=True)

    # Ensure TMPDIR is empty: remove any previous contents (including unix sockets).
    if session_tmp.exists():
        try:
            if session_tmp.is_dir() and not session_tmp.is_symlink():
                shutil.rmtree(session_tmp)
            else:
                session_tmp.unlink()
        except OSError:
            # Best-effort cleanup; we'll try to reuse/create the dir below.
            pass

    session_tmp.mkdir(parents=True, exist_ok=True)
    try:
        session_tmp.chmod(0o700)
    except OSError:
        pass
    try:
        (session_tmp / "teleclaude_session_id").write_text(session_id, encoding="utf-8")
    except OSError:
        pass
    return session_tmp


async def create_tmux_session(
    name: str,
    working_dir: str,
    session_id: Optional[str] = None,
    env_vars: Optional[Dict[str, str]] = None,
) -> bool:
    """Create a new tmux session.

    Tmux automatically uses the $SHELL environment variable to determine which shell to use.
    No explicit shell parameter needed - tmux handles this natively.
    Terminal size is not specified - tmux uses its default (80x24) which is fine for AI TUIs.

    Args:
        name: Session name
        working_dir: Initial working directory
        session_id: TeleClaude session ID (injected as TELECLAUDE_SESSION_ID env var)
        env_vars: Additional environment variables to inject (e.g., TTS voice config)

    Returns:
        True if successful, False otherwise
    """
    try:
        effective_env_vars: Dict[str, str] = dict(env_vars) if env_vars else {}

        # Prevent oh-my-zsh last-working-dir plugin from overriding our -c directory.
        # The plugin auto-restores the last directory when starting in $HOME unless this var is set.
        effective_env_vars["ZSH_LAST_WORKING_DIRECTORY"] = "1"

        # Claude Code can crash on macOS if TMPDIR contains unix sockets (fs.watch EOPNOTSUPP/UNKNOWN).
        # Use a per-session, empty TMPDIR to avoid inheriting sockets from global temp directories.
        if session_id:
            session_tmp_dir = _prepare_session_tmp_dir(session_id)
            effective_env_vars["TMPDIR"] = str(session_tmp_dir)
            effective_env_vars["TMP"] = str(session_tmp_dir)
            effective_env_vars["TEMP"] = str(session_tmp_dir)

        # Create tmux session in detached mode
        # tmux automatically uses $SHELL for the session's shell
        # No need for explicit shell command - tmux creates proper PTY with user's default shell

        logger.info("create_tmux_session: name=%s, working_dir=%s", name, working_dir)
        cmd = [
            config.computer.tmux_binary,
            "new-session",
            "-d",  # Detached
            "-s",
            name,  # Session name
            "-c",
            working_dir,  # Working directory
        ]

        # Inject TeleClaude session ID as env var (for Claude Code hook integration)
        if session_id:
            cmd.extend(["-e", f"TELECLAUDE_SESSION_ID={session_id}"])

        # Inject additional environment variables (e.g., TTS voice configuration)
        if effective_env_vars:
            for var_name, var_value in effective_env_vars.items():
                cmd.extend(["-e", f"{var_name}={var_value}"])

        # Don't capture stdout/stderr - let tmux create its own PTY
        # Using PIPE can leak file descriptors to child processes in tmux
        result = await asyncio.create_subprocess_exec(*cmd)
        await wait_with_timeout(result, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode != 0:
            return False

        # Ensure detach does NOT destroy the session (respect persistent TC sessions).
        try:
            option_cmd = [config.computer.tmux_binary, "set-option", "-t", name, "destroy-unattached", "off"]
            opt_result = await asyncio.create_subprocess_exec(
                *option_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, opt_err = await communicate_with_timeout(opt_result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")
            if opt_result.returncode != 0:
                logger.warning(
                    "Failed to set destroy-unattached off for %s: %s",
                    name,
                    opt_err.decode().strip(),
                )
            hook_cmd = [config.computer.tmux_binary, "set-hook", "-t", name, "client-detached", "run-shell true"]
            hook_result = await asyncio.create_subprocess_exec(
                *hook_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, hook_err = await communicate_with_timeout(hook_result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")
            if hook_result.returncode != 0:
                logger.warning(
                    "Failed to set client-detached hook for %s: %s",
                    name,
                    hook_err.decode().strip(),
                )
        except Exception as e:
            logger.warning("Failed to set destroy-unattached off for %s: %s", name, e)

        return True

    except Exception as e:
        print(f"Error creating tmux session: {e}")
        return False


async def update_tmux_session(session_name: str, env_vars: Dict[str, str]) -> bool:
    """Update environment variables in an existing tmux session.

    Uses tmux setenv to update environment variables. Note: Only NEW processes
    spawned after this update will see the new values. Existing shell processes
    won't see the changes.

    Args:
        session_name: Session name
        env_vars: Dictionary of environment variables to update

    Returns:
        True if successful, False otherwise
    """
    try:
        for var_name, var_value in env_vars.items():
            cmd = [config.computer.tmux_binary, "setenv", "-t", session_name, var_name, var_value]
            result = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

            if result.returncode != 0:
                logger.error(
                    "Failed to set %s in session %s: returncode=%d, stderr=%s",
                    var_name,
                    session_name,
                    result.returncode,
                    stderr.decode().strip(),
                )
                return False

        logger.debug("Updated tmux env vars in %s: %s", session_name, list(env_vars.keys()))
        return True

    except Exception as e:
        logger.error("Exception updating tmux session %s: %s", session_name, e)
        return False


async def send_keys(
    session_name: str,
    text: str,
    session_id: Optional[str] = None,
    working_dir: str = "~",
    send_enter: bool = True,
    active_agent: Optional[str] = None,
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
        if not await session_exists(session_name):
            logger.info("Session %s not found, creating new session...", session_name)
            success = await create_tmux_session(
                name=session_name,
                working_dir=working_dir,
                session_id=session_id,
            )
            if not success:
                logger.error("Failed to create session %s", session_name)
                return False
            logger.info("Created fresh session %s", session_name)

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
    active_agent: Optional[str] = None,
) -> bool:
    """Send keys to an existing tmux session (do not auto-create)."""
    try:
        if not await session_exists(session_name):
            return False
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


def pid_is_alive(pid: int) -> bool:
    """Return True if a PID appears to be alive."""
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


async def get_pane_tty(session_name: str) -> Optional[str]:
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


async def get_pane_pid(session_name: str) -> Optional[int]:
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


async def _send_keys_tmux(
    *,
    session_name: str,
    text: str,
    send_enter: bool,
    active_agent: Optional[str],
) -> bool:
    """Send keys to tmux (session must already exist)."""
    # Gemini CLI can't handle '!' character - escape it
    # See: https://github.com/google-gemini/gemini-cli/issues/4454
    send_text = text.replace("!", r"\!") if active_agent == "gemini" else text

    # Send command (no pipes - don't leak file descriptors)
    # UPDATE: We must capture stderr to debug failures. send-keys is ephemeral and doesn't
    # start a long-lived process that would inherit the pipe, so this is safe.
    # -l flag sends keys literally
    cmd_text = [config.computer.tmux_binary, "send-keys", "-t", session_name, "-l", "--", send_text]
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

    # Small delay to let text be processed
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


async def send_signal(session_name: str, signal: str = "SIGINT") -> bool:
    """Send signal to a tmux session.

    Args:
        session_name: Session name
        signal: Signal name (SIGINT, SIGTERM, SIGKILL)

    Returns:
        True if successful, False otherwise
    """
    try:
        if signal == "SIGKILL":
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
        if signal == "SIGINT":
            key = "C-c"
        elif signal == "SIGTERM":
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


async def capture_pane(session_name: str) -> str:
    """Capture pane output from tmux session.

    Args:
        session_name: Session name

    Returns:
        Captured output as string
    """
    try:
        # -p = print to stdout
        # -S - = capture entire scrollback buffer (from beginning to end)
        # -J = preserve trailing spaces (better for capturing exact output)
        cmd = [config.computer.tmux_binary, "capture-pane", "-t", session_name, "-p", "-J", "-S", "-"]

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

    except Exception as e:
        logger.error("Exception capturing pane from session %s: %s", session_name, e)
        return ""


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


async def list_tmux_sessions() -> List[str]:
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

                    # Get tmux processes
                    tmux_processes = [  # type: ignore[misc]
                        {"pid": p.pid, "create_time": p.create_time()}  # type: ignore[misc]
                        for p in psutil.process_iter(["pid", "name", "create_time"])  # type: ignore[misc]
                        if "tmux" in p.info["name"].lower()  # type: ignore[misc]
                    ]

                    # Get system metrics
                    memory = psutil.virtual_memory()  # type: ignore[misc]
                    cpu_percent = psutil.cpu_percent(interval=0.1)  # type: ignore[misc]

                    logger.error(
                        "Session %s does not exist (died unexpectedly)",
                        session_name,
                        extra={
                            "session_name": session_name,
                            "stderr": stderr.decode().strip(),
                            "tmux_sessions_count": len([s for s in tmux_sessions if s]),
                            "tmux_processes_count": len(tmux_processes),  # type: ignore[misc]
                            "system_memory_used_mb": memory.used // 1024 // 1024,  # type: ignore[misc]
                            "system_memory_percent": memory.percent,  # type: ignore[misc]
                            "system_cpu_percent": cpu_percent,  # type: ignore[misc]
                        },
                    )
                except Exception as diag_error:
                    logger.warning("Failed to capture diagnostics: %s", diag_error)

        return result.returncode == 0

    except Exception as e:
        logger.error("Exception in session_exists for %s: %s", session_name, e)
        return False


async def get_current_command(session_name: str) -> Optional[str]:
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
        # logger.debug("Current command in %s: %s", session_name, command)
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
        return all(pane == "1" for pane in panes)
    except Exception:
        return False


async def get_session_pane_id(session_name: str) -> Optional[str]:
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


async def get_pane_title(session_name: str) -> Optional[str]:
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


async def get_current_directory(session_name: str) -> Optional[str]:
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
