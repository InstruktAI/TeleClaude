"""Terminal bridge for TeleClaude - handles tmux session management."""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

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


class TerminalBridge:
    """Manages tmux terminal sessions."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Initialize terminal bridge.

        Args:
            config: Configuration dictionary with polling settings
        """
        self.config = config or {}

    def _get_lpoll_list(self) -> List[str]:
        """Get long-running process list: defaults + config extensions."""
        defaults = LPOLL_DEFAULT_LIST.copy()
        extensions = self.config.get("polling", {}).get("lpoll_extensions", [])
        return defaults + extensions

    def _is_long_running_command(self, command: str) -> bool:
        """Check if command is a known long-running interactive process.

        Args:
            command: The command string to check

        Returns:
            True if command is in the lpoll list
        """
        lpoll_list = self._get_lpoll_list()
        # Extract first word (command name)
        first_word = command.strip().split()[0] if command.strip() else ""
        first_word_lower = first_word.lower()

        return any(first_word_lower == known.lower() for known in lpoll_list)

    def _has_command_separator(self, command: str) -> bool:
        """Check if command chains multiple commands with separators.

        Args:
            command: The command string to check

        Returns:
            True if command contains chaining separators (;, &&, ||)
        """
        # Only block actual command chaining, not pipes or redirects
        separators = [";", "&&", "||"]
        return any(sep in command for sep in separators)

    async def create_tmux_session(
        self, name: str, shell: str, working_dir: str, cols: int = 80, rows: int = 24
    ) -> bool:
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
        self,
        session_name: str,
        text: str,
        shell: str = "/bin/zsh",
        working_dir: str = "~",
        cols: int = 80,
        rows: int = 24,
        append_exit_marker: bool = True,
    ) -> Tuple[bool, bool, Optional[str]]:
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

        Returns:
            Tuple of (success, is_long_running, error_msg)
            - success: True if command was sent successfully
            - is_long_running: True if command is a long-running interactive process
            - error_msg: Error message if validation failed, None otherwise
        """
        try:
            # Detect if command is long-running interactive process
            is_long_running = self._is_long_running_command(text)

            # Validate: reject command chaining with long-running processes
            if is_long_running and self._has_command_separator(text):
                error_msg = (
                    "⚠️ Cannot chain commands with interactive processes (claude, vim, etc.). Run them separately."
                )
                logger.warning("Rejected command chaining with long-running process: %s", text)
                return False, False, error_msg

            # Check if session exists, create if not
            if not await self.session_exists(session_name):
                logger.info("Session %s not found, creating new session...", session_name)
                success = await self.create_tmux_session(session_name, shell, working_dir, cols, rows)
                if not success:
                    logger.error("Failed to create session %s", session_name)
                    return False, False, None
                logger.info("Created fresh session %s", session_name)

            # Determine whether to append exit marker
            # - Long-running processes: NO marker (they don't exit)
            # - User explicitly disabled: NO marker (sending input to running process)
            # - Otherwise: YES marker (normal shell commands)
            should_append_marker = append_exit_marker and not is_long_running

            if should_append_marker:
                command_with_marker = f'{text}; echo "__EXIT__$?__"'
                logger.debug("Sending command WITH exit marker to %s", session_name)
            else:
                command_with_marker = text
                if is_long_running:
                    logger.debug("Sending long-running command WITHOUT exit marker to %s", session_name)
                else:
                    logger.debug("Sending input WITHOUT exit marker to %s (running process)", session_name)

            # Send command with marker (no pipes - don't leak file descriptors)
            cmd_text = ["tmux", "send-keys", "-t", session_name, command_with_marker]
            result = await asyncio.create_subprocess_exec(*cmd_text)
            await result.wait()

            if result.returncode != 0:
                logger.error("Failed to send text to session %s: returncode=%d", session_name, result.returncode)
                return False, False, None

            # Small delay to let text be processed
            await asyncio.sleep(0.1)

            # Then send C-m (Enter) separately for TUI compatibility (Claude Code, etc)
            cmd_enter = ["tmux", "send-keys", "-t", session_name, "C-m"]
            result = await asyncio.create_subprocess_exec(*cmd_enter)
            await result.wait()

            if result.returncode != 0:
                logger.error("Failed to send Enter to session %s: returncode=%d", session_name, result.returncode)
                return False, False, None

            return True, is_long_running, None

        except Exception as e:
            logger.exception("Error sending keys to tmux session %s: %s", session_name, e)
            return False, False, None

    async def send_signal(self, session_name: str, signal: str = "SIGINT") -> bool:
        """Send signal to a tmux session.

        Args:
            session_name: Session name
            signal: Signal name (SIGINT, SIGTERM, etc.)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Send Ctrl+C for SIGINT, etc.
            if signal == "SIGINT":
                key = "C-c"
            elif signal == "SIGTERM":
                key = "C-\\"
            else:
                return False

            cmd = ["tmux", "send-keys", "-t", session_name, key]
            result = await asyncio.create_subprocess_exec(*cmd)
            await result.wait()

            return result.returncode == 0

        except Exception as e:
            print(f"Error sending signal to tmux: {e}")
            return False

    async def send_escape(self, session_name: str) -> bool:
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

    async def capture_pane(self, session_name: str, lines: Optional[int] = None) -> str:
        """Capture pane output from tmux session.

        Args:
            session_name: Session name
            lines: Number of lines to capture (None = entire scrollback buffer)

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

    async def resize_session(self, session_name: str, cols: int, rows: int) -> bool:
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
                "tmux", "set-environment", "-t", session_name, "COLUMNS", str(cols)
            )
            await p1.wait()
            p2 = await asyncio.create_subprocess_exec("tmux", "set-environment", "-t", session_name, "LINES", str(rows))
            await p2.wait()

            # Resize the window
            cmd = ["tmux", "resize-window", "-t", session_name, "-x", str(cols), "-y", str(rows)]
            result = await asyncio.create_subprocess_exec(*cmd)
            await result.wait()

            return result.returncode == 0

        except Exception as e:
            print(f"Error resizing session: {e}")
            return False

    async def kill_session(self, session_name: str) -> bool:
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

    async def list_tmux_sessions(self) -> List[str]:
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

    async def session_exists(self, session_name: str) -> bool:
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
                logger.info("Session %s exists", session_name)

            return result.returncode == 0

        except Exception as e:
            logger.error("Exception in session_exists for %s: %s", session_name, e)
            return False

    async def rename_session(self, old_name: str, new_name: str) -> bool:
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

    async def get_session_pane_id(self, session_name: str) -> Optional[str]:
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

    async def start_pipe_pane(self, session_name: str, command: str) -> bool:
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

    async def stop_pipe_pane(self, session_name: str) -> bool:
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
