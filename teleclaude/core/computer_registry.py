"""Computer registry with heartbeat mechanism for dynamic discovery.

Each daemon:
- Posts status message to General topic (thread_id=None) with [REGISTRY] prefix
- Updates message every 30s (heartbeat)
- Polls General topic to discover other computers
- Filters for [REGISTRY] messages to ignore other content
- Builds in-memory list of online/offline computers

The General topic is used because it's the only predefined topic that all computers
can access without manual configuration. All registry messages are prefixed with
[REGISTRY] to distinguish them from other General topic content.
"""

import asyncio
import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from instrukt_ai_logging import get_logger
from telegram import Message

from teleclaude.core.db import db
from teleclaude.core.ux_state import (
    get_system_ux_state,
    update_system_ux_state,
)

if TYPE_CHECKING:
    from teleclaude.adapters.telegram_adapter import TelegramAdapter

logger = get_logger(__name__)


class ComputerRegistry:  # pylint: disable=too-many-instance-attributes  # Registry manager needs state for heartbeat and discovery
    """Manages computer discovery via Telegram General topic heartbeats.

    Uses the General topic (thread_id=None) which is accessible to all computers
    without manual configuration. This eliminates the duplicate topic creation problem.

    Each daemon:
    - Posts status message to General topic with [REGISTRY] prefix
    - Updates message every 30s (heartbeat)
    - Polls General topic and filters for [REGISTRY] messages
    - Builds in-memory list of online/offline computers
    """

    def __init__(
        self,
        telegram_adapter: "TelegramAdapter",
        computer_name: str,
        bot_username: str,
    ):
        self.telegram_adapter = telegram_adapter
        self.computer_name = computer_name
        self.bot_username = bot_username

        # In-memory state
        self.computers: dict[str, dict[str, object]] = {}
        self.registry_topic_id: Optional[int] = None
        self.my_ping_message_id: Optional[int] = None  # Message ID for /registry_ping command
        self.my_pong_message_id: Optional[int] = None  # Message ID for [REGISTRY_PONG] response

        # Configuration
        self.heartbeat_interval = 60  # Send /registry_ping every 60s
        self.poll_interval = 60  # Poll registry every 60s
        self.offline_threshold = 120  # Mark offline after 120s of no pong (2 missed heartbeats)

    async def start(self) -> None:
        """Start registry: send initial ping + start background loops."""
        logger.info("Starting computer registry for %s", self.computer_name)

        # Use General topic (thread_id=None) for registry
        self.registry_topic_id = await self._get_or_create_registry_topic()

        # Send initial ping (triggers all bots to respond with pong)
        try:
            await self._send_ping()
            # Also respond to our own ping (bots don't trigger their own command handlers)
            await self.handle_ping_command()
        except Exception as e:
            logger.error("Failed to send initial registry ping: %s", e)
            # Continue anyway - heartbeat will retry

        # Wait a moment for pong responses from other bots to arrive
        await asyncio.sleep(2)

        # Poll once to collect pong responses
        await self._refresh_computer_list()

        # Start background loops
        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._poll_registry_loop())

        logger.info(
            "Computer registry started: General topic (ID=None), discovered %d computers",
            len(self.computers),
        )

    async def _get_or_create_registry_topic(self) -> Optional[int]:
        """Use the General topic (thread_id=None) for registry.

        The General topic is accessible to all computers without manual configuration.
        Returns None to represent the General topic (messages sent without message_thread_id).

        Restores persisted message IDs from previous daemon session.
        """
        # Use None to represent General topic (no message_thread_id parameter)
        topic_id = None

        # Restore message IDs from previous session (if any)
        try:
            ux_state = await get_system_ux_state(db._db)  # type: ignore[arg-type]
            self.my_ping_message_id = ux_state.registry.ping_message_id
            self.my_pong_message_id = ux_state.registry.pong_message_id
            if self.my_ping_message_id or self.my_pong_message_id:
                logger.info(
                    "Restored registry message IDs: ping=%s, pong=%s",
                    self.my_ping_message_id,
                    self.my_pong_message_id,
                )
        except Exception as e:
            logger.warning("Failed to restore registry message IDs: %s", e)
            # Continue with None values (will create new messages)

        logger.info("Using General topic (thread_id=None) for computer registry")
        return topic_id

    async def _heartbeat_loop(self) -> None:
        """Send /registry_ping every N seconds (heartbeat)."""
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await self._send_ping()
                # Also respond to our own ping
                await self.handle_ping_command()
                logger.debug("Heartbeat ping+pong sent for %s", self.computer_name)
            except Exception as e:
                logger.error("Heartbeat ping failed: %s", e)

    async def _poll_registry_loop(self) -> None:
        """Poll registry topic and refresh in-memory computer list every N seconds."""
        while True:
            await asyncio.sleep(self.poll_interval)
            try:
                await self._refresh_computer_list()
                logger.debug(
                    "Registry polled: %d total, %d online",
                    len(self.computers),
                    len([c for c in self.computers.values() if c["status"] == "online"]),
                )
            except Exception as e:
                logger.error("Registry poll failed: %s", e)

    async def _send_ping(self) -> None:
        """Send or edit /registry_ping command to General topic."""
        # Include timestamp so Telegram accepts the edit
        text = f"/registry_ping by {self.bot_username} at {datetime.now().strftime('%H:%M:%S')}"

        if self.my_ping_message_id is None:
            # First time - post new message
            try:
                msg = await self.telegram_adapter.send_message_to_topic(
                    topic_id=self.registry_topic_id, text=text, parse_mode=None
                )
                self.my_ping_message_id = msg.message_id
                logger.debug("Posted ping to registry: message_id=%s", self.my_ping_message_id)

                # Persist message ID
                await update_system_ux_state(
                    db._db,  # type: ignore[arg-type]
                    registry_ping_message_id=self.my_ping_message_id,
                    registry_pong_message_id=self.my_pong_message_id,
                )
            except Exception as e:
                logger.error("Failed to post ping: %s", e)
                raise
        else:
            # Edit existing message (keep General topic clean)
            try:
                edited_message: Message = await self.telegram_adapter.app.bot.edit_message_text(  # type: ignore[assignment,union-attr,misc]
                    chat_id=self.telegram_adapter.supergroup_id,
                    message_id=self.my_ping_message_id,
                    text=text,
                )
                # Cache the edited message (bots don't get updates for their own edits)
                topic_id = self.registry_topic_id
                if topic_id not in self.telegram_adapter._topic_message_cache:
                    self.telegram_adapter._topic_message_cache[topic_id] = []
                # Replace old version
                self.telegram_adapter._topic_message_cache[topic_id] = [
                    m
                    for m in self.telegram_adapter._topic_message_cache[topic_id]
                    if m.message_id != self.my_ping_message_id
                ]
                self.telegram_adapter._topic_message_cache[topic_id].append(edited_message)
            except Exception as e:
                error_lower = str(e).lower()
                # If message was deleted, post new one
                if "message to edit not found" in error_lower or "message not found" in error_lower:
                    logger.warning("Ping message deleted, posting new one")
                    self.my_ping_message_id = None
                    await self._send_ping()
                else:
                    logger.error("Failed to edit ping: %s", e)
                    raise

    async def handle_ping_command(self) -> None:
        """Handle /registry_ping command - respond with /pong command.

        Called by telegram_adapter when /registry_ping command is received.
        All bots respond with /pong command (commands are visible to all bots).
        """
        text = f"/pong by {self.computer_name} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        if self.my_pong_message_id is None:
            # First pong - post new message
            try:
                msg = await self.telegram_adapter.send_message_to_topic(
                    topic_id=self.registry_topic_id, text=text, parse_mode=None
                )
                self.my_pong_message_id = msg.message_id
                logger.debug("Posted pong to registry: message_id=%s", self.my_pong_message_id)

                # Persist message ID
                await update_system_ux_state(
                    db._db,  # type: ignore[arg-type]
                    registry_ping_message_id=self.my_ping_message_id,
                    registry_pong_message_id=self.my_pong_message_id,
                )
            except Exception as e:
                logger.error("Failed to post pong: %s", e)
        else:
            # Edit existing pong message
            try:
                edited_message: Message = await self.telegram_adapter.app.bot.edit_message_text(  # type: ignore[assignment,union-attr,misc]
                    chat_id=self.telegram_adapter.supergroup_id,
                    message_id=self.my_pong_message_id,
                    text=text,
                )
                # Cache the edited message (bots don't get updates for their own edits)
                topic_id = self.registry_topic_id
                if topic_id not in self.telegram_adapter._topic_message_cache:
                    self.telegram_adapter._topic_message_cache[topic_id] = []
                # Replace old version
                self.telegram_adapter._topic_message_cache[topic_id] = [
                    m
                    for m in self.telegram_adapter._topic_message_cache[topic_id]
                    if m.message_id != self.my_pong_message_id
                ]
                self.telegram_adapter._topic_message_cache[topic_id].append(edited_message)
            except Exception as e:
                error_lower = str(e).lower()
                # If message was deleted, post new one
                if "message to edit not found" in error_lower or "message not found" in error_lower:
                    logger.warning("Pong message deleted, posting new one")
                    self.my_pong_message_id = None
                    await self.handle_ping_command()
                else:
                    logger.error("Failed to edit pong: %s", e)

    async def _refresh_computer_list(self) -> None:
        """Poll General topic and parse /pong commands.

        Filters for /pong commands. Commands ARE visible to all bots (unlike regular messages).
        """
        messages = await self.telegram_adapter.get_topic_messages(
            topic_id=self.registry_topic_id,
            limit=100,  # Support up to 100 computers
        )

        now = datetime.now()

        for msg in messages:
            try:
                # Filter for /pong commands (ignore /registry_ping and other messages)
                if not msg.text or not msg.text.startswith("/pong"):
                    continue

                # Parse: "/pong by MozBook at 2025-11-06 01:45:30"
                match = re.match(r"^/pong by (\w+) at ([\d\-: ]+)$", msg.text.strip())
                if not match:
                    continue

                computer_name = match.group(1)
                last_seen_str = match.group(2)
                last_seen = datetime.strptime(last_seen_str, "%Y-%m-%d %H:%M:%S")

                # Determine online status (< offline_threshold = online)
                seconds_ago = (now - last_seen).total_seconds()
                is_online = seconds_ago < self.offline_threshold

                # Extract bot_username from message sender
                # msg.from_user.username should be bot username without @
                bot_username: str | None = f"@{msg.from_user.username}" if msg.from_user else None

                # Update in-memory registry
                self.computers[computer_name] = {
                    "name": computer_name,
                    "bot_username": bot_username,
                    "status": "online" if is_online else "offline",
                    "last_seen": last_seen,
                    "last_seen_ago": f"{int(seconds_ago)}s ago",
                }

            except Exception as e:
                logger.warning("Failed to parse registry pong message: %s", e)

    # === Public API for MCP tools and daemon ===

    def get_online_computers(self) -> list[dict[str, object]]:
        """Get list of currently online computers (for teleclaude__list_computers).

        Returns:
            List of dicts with computer info, sorted by name.
        """
        computers = [c for c in self.computers.values() if c["status"] == "online"]
        return sorted(computers, key=lambda c: str(c["name"]))  # type: ignore[misc]

    def get_all_computers(self) -> list[dict[str, object]]:
        """Get all computers (online + offline), sorted by name."""
        return sorted(self.computers.values(), key=lambda c: str(c["name"]))  # type: ignore[misc]

    def is_computer_online(self, computer_name: str) -> bool:
        """Check if specific computer is currently online."""
        return computer_name in self.computers and self.computers[computer_name]["status"] == "online"

    def get_computer_info(self, computer_name: str) -> Optional[dict[str, object]]:
        """Get info for specific computer (or None if not found)."""
        return self.computers.get(computer_name)
