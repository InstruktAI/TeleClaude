"""Terminal bridge for TeleClaude - handles tmux session management.

All functions are stateless and use config imported from teleclaude.config.
"""

import asyncio
import logging
from typing import List, Optional

from teleclaude.config import config

logger = logging.getLogger(__name__)

# Default list of long-running interactive processes (lpoll)
# These commands will NOT have exit markers appended
LPOLL_DEFAULT_LIST = [
    # Claude Code
    "claude",
    # Text editors
    "vim",
    "vi",
    "nvim",
    "nano",
    "emacs",
    "micro",
    "helix",
    "ed",
    # System monitors
    "top",
    "htop",
    "btop",
    "iotop",
    "nethogs",
    "iftop",
    "glances",
    # Pagers
    "less",
    "more",
    # Interactive shells/REPLs
    "python",
    "python3",
    "node",
    "irb",
    "psql",
    "mysql",
    "redis-cli",
    "mongo",
    "sqlite3",
    # Log viewers (command part only, flags handled separately)
    "tail",
    "journalctl",
    # Interactive tools
    "tmux",
    "screen",
    "fzf",
    "ncdu",
    "ranger",
    "mc",
    # Debuggers
    "gdb",
    "lldb",
    "pdb",
    # Others
    "watch",
    "docker",
    "kubectl",
]


def _get_lpoll_list() -> List[str]:
    """Get long-running process list: defaults + config extensions."""
    defaults = LPOLL_DEFAULT_LIST.copy()
    return defaults + config.polling.lpoll_extensions


def is_long_running_command(command: str) -> bool:
    """Check if command is a known long-running interactive process.

    Args:
        command: The command string to check

    Returns:
        True if command is in the lpoll list
    """
    lpoll_list = _get_lpoll_list()
    # Extract first word (command name)
    first_word = command.strip().split()[0] if command.strip() else ""
    first_word_lower = first_word.lower()

    return any(first_word_lower == known.lower() for known in lpoll_list)


def has_command_separator(command: str) -> bool:
    """Check if command chains multiple commands with separators.

    Args:
        command: The command string to check

    Returns:
        True if command contains chaining separators (;, &&, ||)
    """
    # Only block actual command chaining, not pipes or redirects
    separators = [";", "&&", "||"]
    return any(sep in command for sep in separators)


async def create_tmux_session(name: str, shell: str, working_dir: str, cols: int = 80, rows: int = 24) -> bool:
    """Create a new tmux session.

    Args:
        name: Session name
        shell: Shell to use (e.g., /bin/zsh)
        working_dir: Initial working directory
        cols: Terminal columns
        rows: Terminal rows

    Returns:
        True if successful, False otherwise
    """
    try:
        # Create tmux session in detached mode with login shell
        # tmux creates proper PTYs automatically, no need for manual redirection
        shell_cmd = f"{shell} -l"

        cmd = [
            "tmux",
            "new-session",
            "-d",  # Detached
            "-s",
            name,  # Session name
            "-c",
            working_dir,  # Working directory
            "-x",
            str(cols),  # Width
            "-y",
            str(rows),  # Height
            shell_cmd,
        ]

        # Don't capture stdout/stderr - let tmux create its own PTY
        # Using PIPE can leak file descriptors to child processes in tmux
        result = await asyncio.create_subprocess_exec(*cmd)
        await result.wait()

        return result.returncode == 0

    except Exception as e:
        print(f"Error creating tmux session: {e}")
        return False


async def send_keys(
    session_name: str,
    text: str,
    shell: str = "/bin/zsh",
    working_dir: str = "~",
    cols: int = 80,
    rows: int = 24,
    append_exit_marker: bool = True,
) -> bool:
    """Send keys (text) to a tmux session, creating a new session if needed.

    If the session doesn't exist (crashed or never created), creates a fresh
    session with the same name. Previous state is lost - this is NOT recovery,
    just creating a new session so the user can continue working.

    Args:
        session_name: Session name
        text: Text to send (will be followed by Enter)
        shell: Shell to use if creating new session (default: /bin/zsh)
        working_dir: Working directory if creating new session (default: ~)
        cols: Terminal columns if creating new session (default: 80)
        rows: Terminal rows if creating new session (default: 24)
        append_exit_marker: If True, append exit code marker for command completion detection.
                           Set to False when sending input to a running process. (default: True)

    Returns: bool (success)
    """
    try:
        # Detect if command is long-running interactive process
        is_long_running = is_long_running_command(text)

        # Validate: reject command chaining with long-running processes
        if is_long_running and has_command_separator(text):
            error_msg = "⚠️ Cannot chain commands with interactive processes (claude, vim, etc.). Run them separately."
            logger.warning("Rejected command chaining with long-running process: %s", text)
            raise ValueError(error_msg)

        # Check if session exists, create if not
        if not await session_exists(session_name):
            logger.info("Session %s not found, creating new session...", session_name)
            success = await create_tmux_session(session_name, shell, working_dir, cols, rows)
            if not success:
                logger.error("Failed to create session %s", session_name)
                return False
            logger.info("Created fresh session %s", session_name)

        if not append_exit_marker:
            # Sending input to running process - no marker
            command_text = text
            logger.debug("Sending input WITHOUT exit marker to %s (running process)", session_name)
        else:
            # Append exit marker for reliable completion detection
            # Delta-based polling prevents false detection from old markers
            command_text = f'{text}; echo "__EXIT__$?__"'
            logger.debug("Sending command WITH exit marker to %s", session_name)

        # Send command with marker (no pipes - don't leak file descriptors)
        cmd_text = ["tmux", "send-keys", "-t", session_name, command_text]
        result = await asyncio.create_subprocess_exec(*cmd_text)
        await result.wait()

        if result.returncode != 0:
            logger.error("Failed to send text to session %s: returncode=%d", session_name, result.returncode)
            return False

        # Small delay to let text be processed
        await asyncio.sleep(0.1)

        # Then send C-m (Enter) separately for TUI compatibility (Claude Code, etc)
        cmd_enter = ["tmux", "send-keys", "-t", session_name, "C-m"]
        result = await asyncio.create_subprocess_exec(*cmd_enter)
        await result.wait()

        if result.returncode != 0:
            logger.error("Failed to send Enter to session %s: returncode=%d", session_name, result.returncode)
            return False

        return True

    except Exception as e:
        logger.exception("Error sending keys to tmux session %s: %s", session_name, e)
        return False


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
            cmd = ["tmux", "display-message", "-p", "-t", session_name, "#{pane_pid}"]
            result = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()

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
            stdout, stderr = await result.communicate()

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
            stdout, stderr = await result.communicate()

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

        cmd = ["tmux", "send-keys", "-t", session_name, key]
        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await result.communicate()

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
        cmd = ["tmux", "send-keys", "-t", session_name, "Escape"]
        result = await asyncio.create_subprocess_exec(*cmd)
        await result.wait()

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
        cmd = ["tmux", "send-keys", "-t", session_name, ctrl_key]
        result = await asyncio.create_subprocess_exec(*cmd)
        await result.wait()

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
        cmd = ["tmux", "send-keys", "-t", session_name, "Tab"]
        result = await asyncio.create_subprocess_exec(*cmd)
        await result.wait()

        return result.returncode == 0

    except Exception as e:
        print(f"Error sending tab to tmux: {e}")
        return False


async def send_shift_tab(session_name: str) -> bool:
    """Send SHIFT+TAB (backtab) key to a tmux session.

    Args:
        session_name: Session name

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = ["tmux", "send-keys", "-t", session_name, "BTab"]
        result = await asyncio.create_subprocess_exec(*cmd)
        await result.wait()

        return result.returncode == 0

    except Exception as e:
        print(f"Error sending shift+tab to tmux: {e}")
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
            print(f"Invalid arrow direction: {direction}")
            return False

        # Validate count
        if count < 1:
            print(f"Invalid count: {count} (must be >= 1)")
            return False

        # tmux send-keys with -R flag for repeat
        key_name = valid_directions[direction]
        cmd = ["tmux", "send-keys", "-t", session_name, "-R", str(count), key_name]
        result = await asyncio.create_subprocess_exec(*cmd)
        await result.wait()

        return result.returncode == 0

    except Exception as e:
        print(f"Error sending arrow key ({direction} x{count}) to tmux: {e}")
        return False


async def capture_pane(session_name: str, lines: Optional[int] = None) -> str:
    """Capture pane output from tmux session.

    Args:
        session_name: Session name
        lines: Number of lines to capture from scrollback (None = entire scrollback buffer)

    Returns:
        Captured output as string
    """
    try:
        # -p = print to stdout
        # -S = start line (-10000 = last 10000 lines from scrollback, - = entire history)
        # -J = preserve trailing spaces (better for capturing exact output)
        cmd = ["tmux", "capture-pane", "-t", session_name, "-p", "-J"]

        if lines:
            # Capture specific number of lines from scrollback
            cmd.extend(["-S", f"-{lines}"])
        else:
            # Capture entire scrollback buffer (from beginning to end)
            cmd.extend(["-S", "-"])

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await result.communicate()

        if result.returncode == 0:
            output = stdout.decode("utf-8", errors="replace")
            if not output.strip():
                logger.debug("Captured empty pane from session %s", session_name)
            return output

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


async def resize_session(session_name: str, cols: int, rows: int) -> bool:
    """Resize a tmux session.

    Args:
        session_name: Session name
        cols: New column count
        rows: New row count

    Returns:
        True if successful, False otherwise
    """
    try:
        # Set environment variables for terminal size (no output needed)
        p1 = await asyncio.create_subprocess_exec(
            "tmux", "set-environment", "-t", session_name, "COLUMNS", str(cols), stderr=asyncio.subprocess.PIPE
        )
        await p1.wait()
        p2 = await asyncio.create_subprocess_exec(
            "tmux", "set-environment", "-t", session_name, "LINES", str(rows), stderr=asyncio.subprocess.PIPE
        )
        await p2.wait()

        # Resize the window
        cmd = ["tmux", "resize-window", "-t", session_name, "-x", str(cols), "-y", str(rows)]
        result = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE)
        await result.wait()

        if result.returncode != 0:
            stderr = await result.stderr.read() if result.stderr else b""
            logger.error("Failed to resize tmux session %s: %s", session_name, stderr.decode())

        return result.returncode == 0

    except Exception as e:
        logger.error("Error resizing session %s: %s", session_name, e)
        return False


async def kill_session(session_name: str) -> bool:
    """Kill a tmux session.

    Args:
        session_name: Session name

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = ["tmux", "kill-session", "-t", session_name]
        result = await asyncio.create_subprocess_exec(*cmd)
        await result.wait()

        return result.returncode == 0

    except Exception as e:
        print(f"Error killing session: {e}")
        return False


async def clear_history(session_name: str) -> bool:
    """Clear tmux scrollback history for a session.

    Removes all history from the scrollback buffer, including old exit markers.

    Args:
        session_name: Session name

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = ["tmux", "clear-history", "-t", session_name]
        result = await asyncio.create_subprocess_exec(*cmd)
        await result.wait()

        return result.returncode == 0

    except Exception as e:
        logger.error("Error clearing tmux history for %s: %s", session_name, e)
        return False


async def list_tmux_sessions() -> List[str]:
    """List all tmux sessions.

    Returns:
        List of session names
    """
    try:
        cmd = ["tmux", "list-sessions", "-F", "#{session_name}"]

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await result.communicate()

        if result.returncode == 0:
            sessions = stdout.decode("utf-8").strip().split("\n")
            return [s for s in sessions if s]  # Filter empty strings
        return []

    except Exception as e:
        print(f"Error listing sessions: {e}")
        return []


async def session_exists(session_name: str) -> bool:
    """Check if a tmux session exists.

    Args:
        session_name: Session name

    Returns:
        True if session exists, False otherwise
    """
    try:
        cmd = ["tmux", "has-session", "-t", session_name]

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await result.communicate()

        if result.returncode != 0:
            logger.info(
                "Session %s does not exist: returncode=%d, stderr=%s",
                session_name,
                result.returncode,
                stderr.decode().strip(),
            )
        else:
            logger.debug("Session %s exists", session_name)

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
        cmd = ["tmux", "display-message", "-p", "-t", session_name, "#{pane_current_command}"]

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await result.communicate()

        if result.returncode != 0:
            logger.warning(
                "Failed to get current command for %s: returncode=%d, stderr=%s",
                session_name,
                result.returncode,
                stderr.decode().strip(),
            )
            return None

        command = stdout.decode().strip()
        logger.debug("Current command in %s: %s", session_name, command)
        return command

    except Exception as e:
        logger.error("Exception in get_current_command for %s: %s", session_name, e)
        return None


async def rename_session(old_name: str, new_name: str) -> bool:
    """Rename a tmux session.

    Args:
        old_name: Current session name
        new_name: New session name

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = ["tmux", "rename-session", "-t", old_name, new_name]
        result = await asyncio.create_subprocess_exec(*cmd)
        await result.wait()

        return result.returncode == 0

    except Exception as e:
        print(f"Error renaming session: {e}")
        return False


async def get_session_pane_id(session_name: str) -> Optional[str]:
    """Get the pane ID for a session (for pipe-pane).

    Args:
        session_name: Session name

    Returns:
        Pane ID or None
    """
    try:
        cmd = ["tmux", "list-panes", "-t", session_name, "-F", "#{pane_id}"]

        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await result.communicate()

        if result.returncode == 0:
            pane_id = stdout.decode("utf-8").strip()
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
        cmd = ["tmux", "pipe-pane", "-t", session_name, "-o", command]
        result = await asyncio.create_subprocess_exec(*cmd)
        await result.wait()

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
        cmd = ["tmux", "pipe-pane", "-t", session_name]
        result = await asyncio.create_subprocess_exec(*cmd)
        await result.wait()

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
        cmd = ["tmux", "display-message", "-p", "-t", session_name, "#{pane_title}"]
        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await result.communicate()

        if result.returncode == 0:
            return stdout.decode().strip()

        return None

    except Exception as e:
        logger.error("Failed to get pane title for %s: %s", session_name, e)
        return None
