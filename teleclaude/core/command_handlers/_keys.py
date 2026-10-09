"""Control key and TUI navigation command handlers."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_io
from teleclaude.core.agent_availability import launch_ownership
from teleclaude.core.agent_dispatch import resolve_launch_model
from teleclaude.core.agents import get_agent_command
from teleclaude.core.db import db
from teleclaude.core.injected_text import InjectedInputAuthority
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.core.session_cleanup import host_pane_name
from teleclaude.core.session_environment import build_agent_session_environment
from teleclaude.core.session_launch_profile import resolve_session_launch_profile
from teleclaude.core.session_lifecycle import LifecycleTransition, LifecycleTransitionReason, transition_session
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.core.voice_assignment import get_voice_env_vars
from teleclaude.daemon_session import ensure_tmux_with_identity
from teleclaude.types.commands import KeysCommand

from ._utils import StartPollingFunc, with_session

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
_PANE_BOOTSTRAP_PENDING = "Session pane creation is still in progress"


async def _execute_control_key(
    tmux_action: Callable[..., Awaitable[bool]],
    session: Session,
    *tmux_args: object,
) -> bool:
    """Execute control/navigation key without polling (TUI interaction).

    Used for keys that interact with TUIs and don't produce shell output:
    arrow keys, tab, shift+tab, escape, ctrl, cancel, kill.

    Args:
        tmux_action: Tmux bridge function to execute
        session: Session object (contains tmux_session_name)
        *tmux_args: Additional arguments for tmux_action

    Returns:
        True if tmux action succeeded, False otherwise
    """
    return await tmux_action(session, *tmux_args)


async def _bind_host_pane(session: Session, client: "AdapterClient") -> tuple[Session, str] | None:
    """Ensure the session's host pane exists and is recorded on the row.

    Performs no lifecycle transition; callers own what the binding means for
    the session's lifecycle. Returns the session and its working directory, or
    ``None`` after reporting why no pane could be bound.
    """
    if session.lifecycle_status == SessionLifecycleStatus.INITIALIZING and not session.tmux_session_name:
        raise RuntimeError(_PANE_BOOTSTRAP_PENDING)

    tmux_name = session.tmux_session_name
    if not tmux_name:
        tmux_name = host_pane_name(session.session_id)

    project_path = session.project_path
    subdir = session.subdir

    if not project_path:
        await client.send_message(
            session,
            "❌ Cannot adopt headless session: project_path missing.",
            metadata=MessageMetadata(),
        )
        return None

    try:
        working_dir = resolve_working_dir(project_path, subdir)
    except ValueError as exc:
        await client.send_message(
            session,
            f"❌ Cannot adopt headless session: {exc}",
            metadata=MessageMetadata(),
        )
        return None
    voice = await db.get_voice(session.session_id)
    env_vars = build_agent_session_environment(
        project_path=session.project_path,
        platform_env=get_voice_env_vars(voice) if voice else {},
    )

    try:
        success = await ensure_tmux_with_identity(session, tmux_name, working_dir, env_vars)
    except (OSError, RuntimeError, ValueError) as exc:
        await client.send_message(
            session,
            f"❌ Failed to create tmux session: {exc}",
            metadata=MessageMetadata(),
        )
        return None
    if not success:
        await client.send_message(
            session,
            "❌ Failed to create tmux session for headless session.",
            metadata=MessageMetadata(),
        )
        return None

    if not session.tmux_session_name:
        await db.update_session(session.session_id, tmux_session_name=tmux_name)
        refreshed = await db.get_session(session.session_id)
        if refreshed:
            return refreshed, working_dir
        session.tmux_session_name = tmux_name
    return session, working_dir


async def _ensure_tmux_for_headless(
    session: Session,
    client: "AdapterClient",
    start_polling: StartPollingFunc | None,
    *,
    resume_native: bool,
) -> Session | None:
    """Ensure a headless session has a tmux pane before handling input."""
    if session.tmux_session_name and session.lifecycle_status != "headless":
        return session

    had_pane = bool(session.tmux_session_name)
    bound = await _bind_host_pane(session, client)
    if bound is None:
        return None
    session, working_dir = bound
    tmux_name = session.tmux_session_name

    if not had_pane:
        await transition_session(
            db,
            session.session_id,
            LifecycleTransition(SessionLifecycleStatus.INITIALIZING, LifecycleTransitionReason.ADOPTION_INITIALIZED),
        )
        refreshed = await db.get_session(session.session_id)
        if refreshed:
            session = refreshed

    if resume_native and session.active_agent and session.native_session_id:
        launch = (
            await resolve_launch_model(
                session.active_agent,
                session.thinking_mode,
                ownership=launch_ownership(session.job),
                session_id=session.session_id,
            )
            if session.thinking_mode
            else None
        )
        launch_profile = resolve_session_launch_profile(session, session.active_agent)
        resume_cmd = get_agent_command(
            agent=session.active_agent,
            thinking_mode=session.thinking_mode,
            exec=False,
            native_session_id=session.native_session_id,
            profile=launch_profile.profile,
            launch_flags=launch_profile.flags,
            resolved_flags=launch.flags if launch else None,
        )
        await tmux_io.process_text(
            session,
            resume_cmd,
            working_dir=working_dir,
            active_agent=session.active_agent,
            authority=InjectedInputAuthority.INTERFACE,
        )

    if start_polling:
        await start_polling(session.session_id, tmux_name)

    refreshed = await db.get_session(session.session_id)
    return refreshed or session


async def keys(
    cmd: KeysCommand,
    client: "AdapterClient",
    start_polling: StartPollingFunc,
) -> None:
    """Handle key-based commands via a single KeysCommand."""
    key_name = cmd.key
    session = await db.get_session(cmd.session_id)
    if session and (session.lifecycle_status == "headless"):
        adopted = await _ensure_tmux_for_headless(
            session,
            client,
            start_polling,
            resume_native=True,
        )
        if not adopted:
            return

    if key_name == "cancel":
        await cancel_command(cmd, start_polling, double=False)
        return
    if key_name == "cancel2x":
        await cancel_command(cmd, start_polling, double=True)
        return
    if key_name == "kill":
        await kill_command(cmd, start_polling)
        return
    if key_name == "escape":
        await escape_command(cmd, start_polling, double=False)
        return
    if key_name == "escape2x":
        await escape_command(cmd, start_polling, double=True)
        return
    if key_name == "ctrl":
        await ctrl_command(cmd, client, start_polling)
        return
    if key_name == "tab":
        await tab_command(cmd, start_polling)
        return
    if key_name == "shift_tab":
        await shift_tab_command(cmd, start_polling)
        return
    if key_name == "backspace":
        await backspace_command(cmd, start_polling)
        return
    if key_name == "enter":
        await enter_command(cmd, start_polling)
        return
    if key_name == "key_up":
        await arrow_key_command(cmd, start_polling, "up")
        return
    if key_name == "key_down":
        await arrow_key_command(cmd, start_polling, "down")
        return
    if key_name == "key_left":
        await arrow_key_command(cmd, start_polling, "left")
        return
    if key_name == "key_right":
        await arrow_key_command(cmd, start_polling, "right")
        return

    raise ValueError(f"Unknown keys command: {key_name}")


@with_session
async def cancel_command(
    session: Session,
    _cmd: KeysCommand,
    _start_polling: StartPollingFunc,
    double: bool = False,
) -> None:
    """Send CTRL+C (SIGINT) to a session."""
    success = await _execute_control_key(
        tmux_io.send_signal,
        session,
        "SIGINT",
    )

    if double and success:
        await asyncio.sleep(0.2)
        success = await _execute_control_key(
            tmux_io.send_signal,
            session,
            "SIGINT",
        )

    if success:
        logger.info(
            "Sent %s SIGINT to session %s",
            "double" if double else "single",
            session.session_id,
        )
    else:
        logger.error("Failed to send SIGINT to session %s", session.session_id)


@with_session
async def kill_command(
    session: Session,
    _cmd: KeysCommand,
    _start_polling: StartPollingFunc,
) -> None:
    """Force kill foreground process with SIGKILL (guaranteed termination)."""
    success = await _execute_control_key(
        tmux_io.send_signal,
        session,
        "SIGKILL",
    )

    if success:
        logger.info("Sent SIGKILL to session %s (force kill)", session.session_id)
    else:
        logger.error("Failed to send SIGKILL to session %s", session.session_id)


@with_session
async def escape_command(
    session: Session,
    cmd: KeysCommand,
    start_polling: StartPollingFunc,
    double: bool = False,
) -> None:
    """Send ESCAPE key to a session, optionally followed by text+ENTER."""
    if cmd.args:
        text = " ".join(cmd.args)

        success = await tmux_io.send_escape(session)
        if not success:
            logger.error("Failed to send ESCAPE to session %s", session.session_id)
            return

        if double:
            await asyncio.sleep(0.1)
            success = await tmux_io.send_escape(session)
            if not success:
                logger.error("Failed to send second ESCAPE to session %s", session.session_id)
                return

        await asyncio.sleep(0.1)

        is_process_running = await tmux_io.is_process_running(session)

        active_agent = session.active_agent
        working_dir = resolve_working_dir(session.project_path, session.subdir)
        success = await tmux_io.process_text(
            session,
            text,
            working_dir=working_dir,
            active_agent=active_agent,
            authority=InjectedInputAuthority.INTERFACE,
        )

        if not success:
            logger.error("Failed to send text to session %s", session.session_id)
            return

        await db.update_last_activity(session.session_id)

        if not is_process_running:
            await start_polling(session.session_id, session.tmux_session_name)

        logger.info(
            "Sent %s ESCAPE + '%s' to session %s",
            "double" if double else "single",
            text,
            session.session_id,
        )
        return

    success = await _execute_control_key(
        tmux_io.send_escape,
        session,
    )

    if double and success:
        await asyncio.sleep(0.2)
        success = await _execute_control_key(
            tmux_io.send_escape,
            session,
        )

    if success:
        logger.info(
            "Sent %s ESCAPE to session %s",
            "double" if double else "single",
            session.session_id,
        )
    else:
        logger.error("Failed to send ESCAPE to session %s", session.session_id)


@with_session
async def ctrl_command(
    session: Session,
    cmd: KeysCommand,
    client: "AdapterClient",
    _start_polling: StartPollingFunc,
) -> None:
    """Send CTRL+key combination to a session."""
    if not cmd.args:
        logger.warning("No key argument provided to ctrl command")
        await client.send_message(
            session,
            "Usage: /ctrl <key> (e.g., /ctrl d for CTRL+D)",
            metadata=MessageMetadata(),
        )
        return

    key = cmd.args[0]

    success = await _execute_control_key(
        tmux_io.send_ctrl_key,
        session,
        key,
    )

    if success:
        logger.info("Sent CTRL+%s to session %s", key.upper(), session.session_id)
    else:
        logger.error("Failed to send CTRL+%s to session %s", key.upper(), session.session_id)


@with_session
async def tab_command(
    session: Session,
    _cmd: KeysCommand,
    _start_polling: StartPollingFunc,
) -> None:
    """Send TAB key to a session."""
    success = await _execute_control_key(
        tmux_io.send_tab,
        session,
    )

    if success:
        logger.info("Sent TAB to session %s", session.session_id)
    else:
        logger.error("Failed to send TAB to session %s", session.session_id)


@with_session
async def shift_tab_command(
    session: Session,
    cmd: KeysCommand,
    _start_polling: StartPollingFunc,
) -> None:
    """Send SHIFT+TAB key to a session with optional repeat count."""
    count = 1
    if cmd.args:
        try:
            count = int(cmd.args[0])
            if count < 1:
                logger.warning("Invalid repeat count %d (must be >= 1), using 1", count)
                count = 1
        except ValueError:
            logger.warning("Invalid repeat count '%s', using 1", cmd.args[0])
            count = 1

    success = await _execute_control_key(
        tmux_io.send_shift_tab,
        session,
        count,
    )

    if success:
        logger.info("Sent SHIFT+TAB (x%d) to session %s", count, session.session_id)
    else:
        logger.error("Failed to send SHIFT+TAB to session %s", session.session_id)


@with_session
async def backspace_command(
    session: Session,
    cmd: KeysCommand,
    _start_polling: StartPollingFunc,
) -> None:
    """Send BACKSPACE key to a session with optional repeat count."""
    count = 1
    if cmd.args:
        try:
            count = int(cmd.args[0])
            if count < 1:
                logger.warning("Invalid repeat count %d (must be >= 1), using 1", count)
                count = 1
        except ValueError:
            logger.warning("Invalid repeat count '%s', using 1", cmd.args[0])
            count = 1

    success = await _execute_control_key(
        tmux_io.send_backspace,
        session,
        count,
    )

    if success:
        logger.info("Sent BACKSPACE (x%d) to session %s", count, session.session_id)
    else:
        logger.error("Failed to send BACKSPACE to session %s", session.session_id)


@with_session
async def enter_command(
    session: Session,
    _cmd: KeysCommand,
    _start_polling: StartPollingFunc,
) -> None:
    """Send ENTER key to a session."""
    success = await _execute_control_key(
        tmux_io.send_enter,
        session,
    )

    if success:
        logger.info("Sent ENTER to session %s", session.session_id)
    else:
        logger.error("Failed to send ENTER to session %s", session.session_id)


@with_session
async def arrow_key_command(
    session: Session,
    cmd: KeysCommand,
    _start_polling: StartPollingFunc,
    direction: str,
) -> None:
    """Send arrow key to a session with optional repeat count."""
    count = 1
    if cmd.args:
        try:
            count = int(cmd.args[0])
            if count < 1:
                logger.warning("Invalid repeat count %d (must be >= 1), using 1", count)
                count = 1
        except ValueError:
            logger.warning("Invalid repeat count '%s', using 1", cmd.args[0])
            count = 1

    success = await _execute_control_key(
        tmux_io.send_arrow_key,
        session,
        direction,
        count,
    )

    if success:
        logger.info(
            "Sent %s arrow key (x%d) to session %s",
            direction.upper(),
            count,
            session.session_id,
        )
    else:
        logger.error(
            "Failed to send %s arrow key to session %s",
            direction.upper(),
            session.session_id,
        )
