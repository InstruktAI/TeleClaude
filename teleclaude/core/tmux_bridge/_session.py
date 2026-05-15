"""Tmux session creation, guardrails, and environment management."""

import asyncio
import hashlib
import os
import re
import shutil
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.paths import BIN_DIR, SHELL_DIR, TELECLAUDE_HOME, TMP_SESSIONS_DIR

from ._pane import session_exists
from ._subprocess import SUBPROCESS_TIMEOUT_QUICK, SubprocessTimeoutError, communicate_with_timeout

logger = get_logger(__name__)

_SETUP_STEP_NO_COLOR_DONE = "__tc_setup_no_color_done__"
_SETUP_STEP_DESTROY_DONE = "__tc_setup_destroy_done__"


def _describe_setup_chain_failure(stdout: bytes) -> str:
    """Infer the failed setup step from chain markers emitted by prior steps."""
    output = stdout.decode("utf-8", errors="ignore")
    if _SETUP_STEP_DESTROY_DONE in output:
        return "set-hook client-detached run-shell true"
    if _SETUP_STEP_NO_COLOR_DONE in output:
        return "set-option destroy-unattached off"
    return "set-environment -u NO_COLOR"


def _get_session_tmp_basedir() -> Path:
    override = os.environ.get("TELECLAUDE_SESSION_TMPDIR_BASE")
    if override:
        return Path(override).expanduser()
    return TMP_SESSIONS_DIR


def get_session_tmpdir_base() -> Path:
    """Return the configured base directory for per-session TMPDIRs."""
    return _get_session_tmp_basedir()


def _safe_path_component(value: str) -> str:
    """Return a filesystem-safe path component derived from value."""
    if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value):
        return value
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def safe_session_tmp_component(session_id: str) -> str:
    """Return the path component used for a session TMPDIR."""
    return _safe_path_component(session_id)


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
    return session_tmp


def get_session_tmpdir(session_id: str) -> Path | None:
    """Return the TMPDIR path for an existing session, or None if it doesn't exist."""
    safe_id = _safe_path_component(session_id)
    path = _get_session_tmp_basedir() / safe_id
    return path if path.is_dir() else None


async def _create_tmux_session(
    name: str,
    working_dir: str,
    session_id: str | None = None,
    env_vars: dict[str, str] | None = None,
) -> bool:
    """Create a new tmux session.

    Tmux automatically uses the $SHELL environment variable to determine which shell to use.
    No explicit shell parameter needed - tmux handles this natively.
    Tmux size is not specified - tmux uses its default (80x24) which is fine for AI TUIs.

    Args:
        name: Session name
        working_dir: Initial working directory
        session_id: TeleClaude session ID (used for per-session temp directory)
        env_vars: Additional environment variables to inject (e.g., TTS voice config)

    Returns:
        True if successful, False otherwise
    """
    try:
        effective_env_vars: dict[str, str] = dict(env_vars) if env_vars else {}

        # Prevent oh-my-zsh last-working-dir plugin from overriding our -c directory.
        # The plugin auto-restores the last directory when starting in $HOME unless this var is set.
        effective_env_vars["ZSH_LAST_WORKING_DIRECTORY"] = "1"

        # Pin the shell environment that agent CLIs and every subshell they
        # spawn will land in. SHELL routes any CLI honoring it to our
        # exec-wrapper; ZDOTDIR/BASH_ENV/ENV route every zsh/bash/sh -c
        # through our minimal rc tree, which prepends ~/.teleclaude/bin once.
        # This is the single mechanism for PATH ordering — no parallel tmux -e
        # PATH injection, no duplicate entries when a child (e.g. codex)
        # rewrites PATH and our .zshenv re-prepends in its subshell.
        #
        # TELECLAUDE_HOME is propagated explicitly so the wrapper and rc
        # files (which all read it with a `${HOME}/.teleclaude` fallback)
        # resolve to the same root the daemon is configured for. Without
        # this, an override-rooted daemon would launch the correctly-pathed
        # wrapper only to have the wrapper reset PATH/ZDOTDIR/etc. back to
        # the default root via the fallback.
        shell_dir = str(SHELL_DIR)
        effective_env_vars["TELECLAUDE_HOME"] = str(TELECLAUDE_HOME)
        effective_env_vars["SHELL"] = str(BIN_DIR / "teleclaude-shell")
        effective_env_vars["ZDOTDIR"] = shell_dir
        effective_env_vars["BASH_ENV"] = f"{shell_dir}/.bashenv"
        effective_env_vars["ENV"] = f"{shell_dir}/.profile"

        # Enable truecolor for CLI agents.  Without this, CLIs (Gemini, Claude,
        # Codex) fall back to 256-color or plain text because TERM=tmux-256color
        # alone does not advertise truecolor.
        effective_env_vars["COLORTERM"] = "truecolor"

        # Prevent `uv run` from auto-syncing the project venv inside worker
        # sessions. Ambient sync while the daemon holds modules loaded causes
        # stale-module ImportError crashes. Explicit `uv sync` still works.
        effective_env_vars["UV_NO_SYNC"] = "1"

        # Claude Code can crash on macOS if TMPDIR contains unix sockets (fs.watch EOPNOTSUPP/UNKNOWN).
        # Use a per-session, empty TMPDIR to avoid inheriting sockets from global temp directories.
        if session_id:
            session_tmp_dir = await asyncio.to_thread(_prepare_session_tmp_dir, session_id)
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

        # Inject additional environment variables (e.g., TTS voice configuration)
        if effective_env_vars:
            for var_name, var_value in effective_env_vars.items():
                cmd.extend(["-e", f"{var_name}={var_value}"])

        # Capture stderr for diagnostics on failure (no special handling otherwise).
        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

        if result.returncode != 0:
            logger.error(
                "tmux new-session failed for %s: returncode=%d stderr=%s",
                name,
                result.returncode,
                stderr.decode().strip() if stderr else "",
            )
            return False

        # Strip NO_COLOR from the session environment as a safe default.
        # The variable is often re-set by the TUI pane manager for peaceful theming,
        # but agent CLIs need ANSI output available while they run inside the tmux pane.
        cmd_setup = [
            config.computer.tmux_binary,
            "set-environment",
            "-t",
            name,
            "-u",
            "NO_COLOR",
            ";",
            "run-shell",
            f"printf {_SETUP_STEP_NO_COLOR_DONE}",
            ";",
            "set-option",
            "-t",
            name,
            "destroy-unattached",
            "off",
            ";",
            "run-shell",
            f"printf {_SETUP_STEP_DESTROY_DONE}",
            ";",
            "set-hook",
            "-t",
            name,
            "client-detached",
            "run-shell true",
        ]
        try:
            setup_result = await asyncio.create_subprocess_exec(
                *cmd_setup, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            setup_out, setup_err = await communicate_with_timeout(
                setup_result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux session setup chain"
            )
            if setup_result.returncode != 0:
                failed_step = _describe_setup_chain_failure(setup_out)
                logger.warning(
                    "Session setup command failed for %s: step=%s stderr=%s",
                    name,
                    failed_step,
                    setup_err.decode().strip(),
                )
        except (OSError, ValueError, SubprocessTimeoutError) as e:
            logger.warning("Session setup chain exception for %s: %s", name, e)

        return True

    except (OSError, ValueError, SubprocessTimeoutError) as e:
        print(f"Error creating tmux session: {e}")
        return False


async def ensure_tmux_session(
    name: str,
    *,
    working_dir: str = "~",
    session_id: str | None = None,
    env_vars: dict[str, str] | None = None,
) -> bool:
    """Ensure a tmux session exists, creating it if missing.

    This is the single choke point for tmux session creation. It is idempotent:
    if the session already exists, returns True without creating.
    """
    try:
        if await session_exists(name, log_missing=False):
            return True

        success = await _create_tmux_session(
            name=name,
            working_dir=working_dir,
            session_id=session_id,
            env_vars=env_vars,
        )
        if success:
            return True

        # If creation failed, re-check existence to handle race/duplicate creation.
        return await session_exists(name, log_missing=False)

    except (OSError, ValueError, SubprocessTimeoutError) as e:
        logger.error("Exception ensuring tmux session %s: %s", name, e)
        return False


async def update_tmux_session(session_name: str, env_vars: dict[str, str]) -> bool:
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

    except (OSError, ValueError, SubprocessTimeoutError) as e:
        logger.error("Exception updating tmux session %s: %s", session_name, e)
        return False
