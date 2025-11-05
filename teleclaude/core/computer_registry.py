"""Computer registry with heartbeat mechanism for dynamic discovery.

Each daemon:
- Posts status message to registry topic
- Updates message every 30s (heartbeat)
- Polls registry to discover other computers
- Builds in-memory list of online/offline computers
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Optional

from teleclaude.core.ux_state import UXStateContext, get_ux_state, update_ux_state

logger = logging.getLogger(__name__)


class ComputerRegistry:
    """Manages computer discovery via Telegram heartbeat topic.

    Each daemon:
    - Posts status message to registry topic
    - Updates message every 30s (heartbeat)
    - Polls registry to discover other computers
    - Builds in-memory list of online/offline computers
    """

    def __init__(
        self, telegram_adapter: Any, computer_name: str, bot_username: str, config: dict[str, Any], session_manager: Any
    ):
        self.telegram_adapter = telegram_adapter
        self.computer_name = computer_name
        self.bot_username = bot_username
        self.config = config
        self.session_manager = session_manager

        # In-memory state
        self.computers: dict[str, dict[str, Any]] = {}
        self.registry_topic_id: Optional[int] = None
        self.my_message_id: Optional[int] = None

        # Configuration
        self.heartbeat_interval = 30  # Update status every 30s
        self.poll_interval = 30  # Poll registry every 30s
        self.offline_threshold = 60  # Mark offline after 60s of no heartbeat

    async def start(self) -> None:
        """Start registry: post status + start background loops."""
        logger.info("Starting computer registry for %s", self.computer_name)

        # Find or create registry topic
        self.registry_topic_id = await self._get_or_create_registry_topic()

        # Post initial status (with fallback to create new topic if current one is stale)
        try:
            await self._update_my_status()
        except Exception as e:
            error_lower = str(e).lower()
            logger.debug(
                "Startup post error: %s (type: %s, checking for: 'thread not found')", error_lower, type(e).__name__
            )
            if "thread not found" in error_lower:
                logger.warning("Registry topic %s not found, creating new topic", self.registry_topic_id)
                try:
                    # Force create new topic and reset state
                    topic = await self.telegram_adapter.create_topic("Online Now")
                    self.registry_topic_id = topic.message_thread_id
                    self.my_message_id = None  # Reset to force new message in new topic
                    logger.info("Created new registry topic during startup: %s", self.registry_topic_id)
                    await update_ux_state(
                        self.session_manager._db,
                        UXStateContext.SYSTEM,
                        {"registry": {"topic_id": self.registry_topic_id}},
                    )
                    # Retry posting status
                    await self._update_my_status()
                    logger.info("Successfully posted to new registry topic during startup")
                except Exception as topic_error:
                    logger.error("Failed to recreate registry topic during startup: %s", topic_error)
                    # Continue anyway - heartbeat will retry
            else:
                logger.error("Failed to post initial registry status: %s", e)
                # Continue anyway - heartbeat will retry

        # Immediately poll once to get current state
        await self._refresh_computer_list()

        # Start background loops
        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._poll_registry_loop())

        logger.info(
            "Computer registry started: topic_id=%s, discovered %d computers",
            self.registry_topic_id,
            len(self.computers),
        )

    async def _get_or_create_registry_topic(self) -> int:
        """Find or create the 'Online Now' topic.

        Uses database persistence to avoid creating duplicate topics on restart.
        Also loads persisted message_id if available.
        """
        registry_name = "Online Now"

        # Load UX state from database (system context)
        ux_state = await get_ux_state(self.session_manager._db, UXStateContext.SYSTEM)
        registry_state = ux_state.get("registry", {})
        stored_topic_id = registry_state.get("topic_id")
        stored_message_id = registry_state.get("message_id")

        if stored_topic_id:
            logger.info("Using stored registry topic ID: %s", stored_topic_id)
            # Restore message_id if available (prevents duplicate messages on restart)
            if stored_message_id:
                self.my_message_id = stored_message_id
                logger.info("Restored message ID from database: %s", stored_message_id)
            return stored_topic_id

        # Create new topic
        logger.info("Creating new registry topic: %s", registry_name)
        topic = await self.telegram_adapter.create_topic(registry_name)
        topic_id = topic.message_thread_id

        # Store topic ID in database for future restarts (system context)
        await update_ux_state(self.session_manager._db, UXStateContext.SYSTEM, {"registry": {"topic_id": topic_id}})

        return topic_id

    async def _heartbeat_loop(self) -> None:
        """Edit our status message every N seconds (heartbeat)."""
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await self._update_my_status()
                logger.debug("Heartbeat sent for %s", self.computer_name)
            except Exception as e:
                logger.error("Heartbeat update failed: %s", e)

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

    async def _update_my_status(self) -> None:
        """Post or edit our status message in registry topic."""
        text = self._format_status_message()

        if self.my_message_id is None:
            # First time - post new message
            try:
                msg = await self.telegram_adapter.send_message_to_topic(
                    topic_id=self.registry_topic_id, text=text, parse_mode=None
                )
                self.my_message_id = msg.message_id
                logger.info("Posted initial status to registry: message_id=%s", self.my_message_id)

                # Persist message_id to prevent duplicate messages on restart (system context)
                await update_ux_state(
                    self.session_manager._db,
                    UXStateContext.SYSTEM,
                    {"registry": {"topic_id": self.registry_topic_id, "message_id": self.my_message_id}},
                )
            except Exception as e:
                logger.error("Failed to post initial status: %s (type: %s)", e, type(e).__name__)
                raise
        else:
            # Update existing message (heartbeat)
            # Use bot API directly since adapter's edit_message expects session_id
            # Don't pass parse_mode to use plain text (Telegram API default)
            try:
                await self.telegram_adapter.app.bot.edit_message_text(
                    chat_id=self.telegram_adapter.supergroup_id,
                    message_id=self.my_message_id,
                    text=text,
                )
            except Exception as e:
                error_lower = str(e).lower()
                logger.debug("Heartbeat edit error: %s (checking for: 'thread not found')", error_lower)

                # If topic/channel not found, recreate it
                if "thread not found" in error_lower or "topic not found" in error_lower:
                    logger.warning("Registry topic %s not found during heartbeat, recreating", self.registry_topic_id)
                    try:
                        topic = await self.telegram_adapter.create_topic("Online Now")
                        self.registry_topic_id = topic.message_thread_id
                        self.my_message_id = None  # Reset to force new message in new topic
                        logger.info("Created new registry topic: %s", self.registry_topic_id)
                        await update_ux_state(
                            self.session_manager._db,
                            UXStateContext.SYSTEM,
                            {"registry": {"topic_id": self.registry_topic_id}},
                        )
                        # Recursively call to post new message
                        await self._update_my_status()
                        logger.info("Successfully posted to new registry topic")
                    except Exception as topic_error:
                        logger.error("Failed to recreate registry topic: %s", topic_error)
                        # Don't raise - let heartbeat retry later
                        return

                # If message not found (deleted from Telegram), post new message
                elif "message to edit not found" in error_lower or "message not found" in error_lower:
                    logger.warning("Heartbeat message %s not found, posting new message", self.my_message_id)
                    try:
                        self.my_message_id = None  # Reset to force new message
                        # Recursively call to post new message
                        await self._update_my_status()
                        logger.info("Successfully posted new heartbeat message")
                    except Exception as post_error:
                        post_error_lower = str(post_error).lower()
                        # If topic also missing, recreate it
                        if "thread not found" in post_error_lower or "topic not found" in post_error_lower:
                            logger.warning("Registry topic also missing, recreating during message recovery")
                            try:
                                topic = await self.telegram_adapter.create_topic("Online Now")
                                self.registry_topic_id = topic.message_thread_id
                                logger.info("Created new registry topic: %s", self.registry_topic_id)
                                await update_ux_state(
                                    self.session_manager._db,
                                    UXStateContext.SYSTEM,
                                    {"registry": {"topic_id": self.registry_topic_id}},
                                )
                                # Try one more time to post
                                await self._update_my_status()
                                logger.info("Successfully posted to recreated topic")
                            except Exception as recreate_error:
                                logger.error("Failed to recreate topic and post: %s", recreate_error)
                        else:
                            logger.error("Failed to post new heartbeat message: %s", post_error)
                        # Don't raise - let heartbeat retry later
                        return

                else:
                    logger.error("Heartbeat update failed: %s", e)
                    # Don't raise - let heartbeat retry later
                    return

    def _format_status_message(self) -> str:
        """Format status message for registry (simple single line)."""
        return f"{self.computer_name} - last seen at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    async def _refresh_computer_list(self) -> None:
        """Poll 'Online Now' topic and parse all computer statuses."""
        messages = await self.telegram_adapter.get_topic_messages(
            topic_id=self.registry_topic_id, limit=100  # Support up to 100 computers
        )

        now = datetime.now()

        for msg in messages:
            try:
                # Parse: "computer_name - last seen at 2025-11-04 15:30:45"
                match = re.match(r"^(\w+) - last seen at ([\d\-: ]+)$", msg.text.strip())
                if not match:
                    continue

                computer_name = match.group(1)
                last_seen_str = match.group(2)
                last_seen = datetime.strptime(last_seen_str, "%Y-%m-%d %H:%M:%S")

                # Determine online status (< offline_threshold = online)
                seconds_ago = (now - last_seen).total_seconds()
                is_online = seconds_ago < self.offline_threshold

                # Extract bot_username from message sender
                # msg.from_user.username should be "teleclaude_macbook_bot"
                bot_username = f"@{msg.from_user.username}" if msg.from_user else None

                # Update in-memory registry
                self.computers[computer_name] = {
                    "name": computer_name,
                    "bot_username": bot_username,
                    "status": "online" if is_online else "offline",
                    "last_seen": last_seen,
                    "last_seen_ago": f"{int(seconds_ago)}s ago",
                }

            except Exception as e:
                logger.warning("Failed to parse registry message: %s", e)

    # === Public API for MCP tools and daemon ===

    def get_online_computers(self) -> list[dict[str, Any]]:
        """Get list of currently online computers (for teleclaude__list_computers).

        Returns:
            List of dicts with computer info, sorted by name.
        """
        computers = [c for c in self.computers.values() if c["status"] == "online"]
        return sorted(computers, key=lambda c: c["name"])

    def get_all_computers(self) -> list[dict[str, Any]]:
        """Get all computers (online + offline), sorted by name."""
        return sorted(self.computers.values(), key=lambda c: c["name"])

    def is_computer_online(self, computer_name: str) -> bool:
        """Check if specific computer is currently online."""
        return computer_name in self.computers and self.computers[computer_name]["status"] == "online"

    def get_computer_info(self, computer_name: str) -> Optional[dict[str, Any]]:
        """Get info for specific computer (or None if not found)."""
        return self.computers.get(computer_name)
