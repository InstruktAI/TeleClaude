"""Control key and TUI navigation command handlers."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge, tmux_io
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.core.session_cleanup import TMUX_SESSION_PREFIX
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.core.voice_assignment import get_voice_env_vars
from teleclaude.types.commands import KeysCommand

from ._utils import StartPollingFunc, with_session

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


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

    tmux_name = session.tmux_session_name
    if not tmux_name:
        tmux_name = f"{TMUX_SESSION_PREFIX}{session.session_id}"
        await db.update_session(
            session.session_id,
            tmux_session_name=tmux_name,
            lifecycle_status="initializing",
        )
        refreshed = await db.get_session(session.session_id)
        if refreshed:
            session = refreshed
        else:
            session.tmux_session_name = tmux_name

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
    except Exception as exc:
        await client.send_message(
            session,
            f"❌ Cannot adopt headless session: {exc}",
            metadata=MessageMetadata(),
        )
        return None
    voice = await db.get_voice(session.session_id)
    env_vars = get_voice_env_vars(voice) if voice else {}

    try:
        created = await tmux_bridge.ensure_tmux_session(
            name=tmux_name,
            working_dir=working_dir,
            session_id=session.session_id,
            env_vars=env_vars,
        )
    except Exception as exc:
        await client.send_message(
            session,
            f"❌ Failed to create tmux session: {exc}",
            metadata=MessageMetadata(),
        )
        return None
    if not created:
        await client.send_message(
            session,
            "❌ Failed to create tmux session for headless session.",
            metadata=MessageMetadata(),
        )
        return None

    if resume_native and session.active_agent and session.native_session_id:
        from teleclaude.core.agents import get_agent_command

        resume_cmd = get_agent_command(
            agent=session.active_agent,
            thinking_mode=session.thinking_mode,
            exec=False,
            native_session_id=session.native_session_id,
        )
        wrapped = tmux_io.wrap_bracketed_paste(resume_cmd, active_agent=session.active_agent)
        await tmux_io.process_text(
            session,
            wrapped,
            working_dir=working_dir,
            active_agent=session.active_agent,
        )

    if start_polling:
        await start_polling(session.session_id, tmux_name)

    await db.update_session(session.session_id, lifecycle_status="active")
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

        sanitized_text = tmux_io.wrap_bracketed_paste(text, active_agent=active_agent)
        working_dir = resolve_working_dir(session.project_path, session.subdir)
        success = await tmux_io.process_text(
            session,
            sanitized_text,
            working_dir=working_dir,
            active_agent=active_agent,
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
