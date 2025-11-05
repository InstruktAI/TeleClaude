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
        self, telegram_adapter: Any, computer_name: str, bot_username: str, config: dict, session_manager: Any
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

    async def start(self):
        """Start registry: post status + start background loops."""
        logger.info("Starting computer registry for %s", self.computer_name)

        # Find or create registry topic
        self.registry_topic_id = await self._get_or_create_registry_topic()

        # Post initial status
        await self._update_my_status()

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
        """
        registry_name = "Online Now"

        # Check if we have stored topic ID in database
        stored_topic_id = await self._get_stored_registry_topic_id()
        if stored_topic_id:
            logger.info("Using stored registry topic ID: %s", stored_topic_id)
            return stored_topic_id

        # Create new topic
        logger.info("Creating new registry topic: %s", registry_name)
        topic = await self.telegram_adapter.create_topic(registry_name)
        topic_id = topic.message_thread_id

        # Store topic ID in database for future restarts
        await self._store_registry_topic_id(topic_id)

        return topic_id

    async def _heartbeat_loop(self):
        """Edit our status message every N seconds (heartbeat)."""
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await self._update_my_status()
                logger.debug("Heartbeat sent for %s", self.computer_name)
            except Exception as e:
                logger.error("Heartbeat update failed: %s", e)

    async def _poll_registry_loop(self):
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

    async def _update_my_status(self):
        """Post or edit our status message in registry topic."""
        text = self._format_status_message()

        if self.my_message_id is None:
            # First time - post new message
            msg = await self.telegram_adapter.send_message_to_topic(
                topic_id=self.registry_topic_id, text=text, parse_mode="Markdown"
            )
            self.my_message_id = msg.message_id
            logger.info("Posted initial status to registry: message_id=%s", self.my_message_id)
        else:
            # Update existing message (heartbeat)
            # Use bot API directly since adapter's edit_message expects session_id
            await self.telegram_adapter.app.bot.edit_message_text(
                chat_id=self.telegram_adapter.supergroup_id,
                message_id=self.my_message_id,
                text=text,
                parse_mode="Markdown",
            )

    def _format_status_message(self) -> str:
        """Format status message for registry (simple single line)."""
        return f"{self.computer_name} - last seen at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    async def _refresh_computer_list(self):
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

    def get_online_computers(self) -> list[dict]:
        """Get list of currently online computers (for teleclaude__list_computers).

        Returns:
            List of dicts with computer info, sorted by name.
        """
        computers = [c for c in self.computers.values() if c["status"] == "online"]
        return sorted(computers, key=lambda c: c["name"])

    def get_all_computers(self) -> list[dict]:
        """Get all computers (online + offline), sorted by name."""
        return sorted(self.computers.values(), key=lambda c: c["name"])

    def is_computer_online(self, computer_name: str) -> bool:
        """Check if specific computer is currently online."""
        return computer_name in self.computers and self.computers[computer_name]["status"] == "online"

    def get_computer_info(self, computer_name: str) -> Optional[dict]:
        """Get info for specific computer (or None if not found)."""
        return self.computers.get(computer_name)

    async def _get_stored_registry_topic_id(self) -> Optional[int]:
        """Get registry topic ID from database.

        Returns:
            Topic ID if stored, None otherwise.
        """
        try:
            cursor = await self.session_manager._db.execute(
                "SELECT value FROM system_settings WHERE key = 'registry_topic_id'"
            )
            row = await cursor.fetchone()
            if row:
                return int(row[0])
            return None
        except Exception as e:
            logger.warning("Failed to retrieve stored registry topic ID: %s", e)
            return None

    async def _store_registry_topic_id(self, topic_id: int):
        """Store registry topic ID in database for persistence across restarts.

        Args:
            topic_id: Telegram topic ID to store
        """
        try:
            await self.session_manager._db.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES ('registry_topic_id', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (str(topic_id),),
            )
            await self.session_manager._db.commit()
            logger.info("Stored registry topic ID in database: %s", topic_id)
        except Exception as e:
            logger.error("Failed to store registry topic ID: %s", e)
