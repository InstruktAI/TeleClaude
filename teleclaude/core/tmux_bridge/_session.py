"""Tmux session creation, guardrails, and environment management."""

import asyncio
import hashlib
import os
import re
import shutil
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config import config

from ._pane import session_exists
from ._subprocess import SUBPROCESS_TIMEOUT_QUICK, communicate_with_timeout

logger = get_logger(__name__)


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

        # Ensure TeleClaude bin is first in PATH so agent-session git/gh wrappers
        # enforce version-control guardrails in every tmux-created session.
        # Always set PATH explicitly for the session; tmux server env can differ
        # from daemon env, so conditional omission is unsafe.
        teleclaude_bin = str(Path.home() / ".teleclaude" / "bin")
        current_path = os.environ.get("PATH", "/usr/bin:/bin")
        path_parts = [part for part in current_path.split(os.pathsep) if part]
        # Always prepend teleclaude_bin to first position, removing duplicates.
        # Even when already present, it may not be first — macOS path_helper
        # and shell startup can reorder PATH after tmux -e injection.
        deduped = [p for p in path_parts if p != teleclaude_bin]
        effective_env_vars["PATH"] = os.pathsep.join([teleclaude_bin] + deduped)

        # Enable truecolor for CLI agents.  Without this, CLIs (Gemini, Claude,
        # Codex) fall back to 256-color or plain text because TERM=tmux-256color
        # alone does not advertise truecolor.
        effective_env_vars["COLORTERM"] = "truecolor"

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
        # The variable is inherited from the parent shell; removing it here
        # lets CLIs emit colors.  The TUI pane manager may re-set NO_COLOR=1
        # for peaceful theming levels (0, 1) when the pane is displayed.
        try:
            unset_cmd = [config.computer.tmux_binary, "set-environment", "-t", name, "-u", "NO_COLOR"]
            unset_result = await asyncio.create_subprocess_exec(
                *unset_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await communicate_with_timeout(unset_result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")
        except Exception:
            pass  # Best-effort; color loss is cosmetic, not critical.

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

        await _apply_shell_guardrails(name, teleclaude_bin)

        return True

    except Exception as e:
        print(f"Error creating tmux session: {e}")
        return False


async def _apply_shell_guardrails(session_name: str, teleclaude_bin: str) -> None:
    """Send post-init shell guardrails via tmux send-keys.

    macOS zsh login shell startup (/etc/zprofile → path_helper, ~/.zshenv, ~/.zprofile)
    rewrites PATH after tmux's -e injection, pushing ~/.teleclaude/bin down. oh-my-zsh's
    github plugin also sets `alias git=hub`, bypassing PATH entirely.

    These keystrokes queue in the PTY input buffer and execute after shell init completes
    but before any agent CLI command arrives (sequential async ordering in bootstrap_session).
    """
    try:
        guardrail_cmd = f'export PATH="{teleclaude_bin}:$PATH"; unalias git 2>/dev/null; clear'
        cmd_text = [
            config.computer.tmux_binary,
            "send-keys",
            "-t",
            session_name,
            "-l",
            "--",
            guardrail_cmd,
        ]
        result = await asyncio.create_subprocess_exec(
            *cmd_text, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux guardrail text")
        if result.returncode != 0:
            logger.warning(
                "Shell guardrail text failed for %s: %s",
                session_name,
                stderr.decode().strip() if stderr else "",
            )
            return

        await asyncio.sleep(0.2)

        cmd_enter = [config.computer.tmux_binary, "send-keys", "-t", session_name, "C-m"]
        result = await asyncio.create_subprocess_exec(
            *cmd_enter, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await communicate_with_timeout(result, None, SUBPROCESS_TIMEOUT_QUICK, "tmux guardrail enter")
        if result.returncode != 0:
            logger.warning(
                "Shell guardrail enter failed for %s: %s",
                session_name,
                stderr.decode().strip() if stderr else "",
            )
    except Exception as e:
        logger.warning("Shell guardrails failed for %s: %s", session_name, e)


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

    except Exception as e:
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

    except Exception as e:
        logger.error("Exception updating tmux session %s: %s", session_name, e)
        return False
