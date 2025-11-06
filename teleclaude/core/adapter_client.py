"""Unified client managing multiple adapters per session.

This module provides AdapterClient, which abstracts adapter complexity behind
a clean, unified interface for the daemon and MCP server.
"""

import logging
import os
from typing import Any, Dict, List, Optional

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.config import get_config

logger = logging.getLogger(__name__)


class AdapterClient:
    """Unified interface for multi-adapter operations.

    Manages multiple adapters (Telegram, Redis, etc.) and provides a clean,
    adapter-agnostic API. Owns the complete adapter lifecycle.

    Key responsibilities:
    - Adapter creation and registration
    - Adapter lifecycle management
    - Peer discovery aggregation from all adapters
    - (Future) Session-aware routing
    - (Future) Parallel broadcasting to multiple adapters
    """

    def __init__(self, daemon: Any = None):
        """Initialize AdapterClient and optionally load adapters.

        Args:
            daemon: Daemon instance (provides session_manager and callbacks).
                   If None, adapters must be registered manually (for testing).
        """
        self.daemon = daemon
        self.adapters: Dict[str, BaseAdapter] = {}  # adapter_type -> adapter instance

        # Load adapters from config if daemon provided
        if daemon:
            self._load_adapters()

    def _load_adapters(self) -> None:
        """Load and initialize adapters from config."""
        config = get_config()

        # Load Telegram adapter if configured
        if "telegram" in config.get("adapters", {}) or os.getenv("TELEGRAM_BOT_TOKEN"):
            telegram_adapter = TelegramAdapter(self.daemon.session_manager, self.daemon)

            # Register callbacks from daemon
            telegram_adapter.on_command(self.daemon.handle_command)
            telegram_adapter.on_message(self.daemon.handle_message)
            telegram_adapter.on_voice(self.daemon.handle_voice)
            telegram_adapter.on_topic_closed(self.daemon.handle_topic_closed)

            self.adapters["telegram"] = telegram_adapter
            logger.info("Loaded Telegram adapter")

        # TODO: Load Redis adapter if configured
        # TODO: Load other adapters

        # Validate at least one adapter is loaded
        if not self.adapters:
            raise ValueError("No adapters configured - check config.yml and .env")

        logger.info("Loaded %d adapter(s): %s", len(self.adapters), list(self.adapters.keys()))

    def register_adapter(self, adapter_type: str, adapter: BaseAdapter) -> None:
        """Manually register an adapter (for testing).

        Args:
            adapter_type: Adapter type name ('telegram', 'redis', etc.)
            adapter: Adapter instance implementing BaseAdapter
        """
        self.adapters[adapter_type] = adapter
        logger.info("Registered adapter: %s", adapter_type)

    async def send_message(self, session_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Send message to session via appropriate adapter(s).

        Messages are sent to the session's primary adapter, then broadcast
        to all secondary adapters with feedback_only=True to prevent loops.

        Args:
            session_id: Session identifier
            text: Message text
            metadata: Optional adapter-specific metadata

        Returns:
            message_id from primary adapter
        """
        # Get session to determine primary adapter
        session = await self.daemon.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        primary_adapter_type = session.adapter_type
        primary_adapter = self.adapters.get(primary_adapter_type)
        if not primary_adapter:
            raise ValueError(f"No adapter for type '{primary_adapter_type}'")

        # Send to primary adapter (full message)
        message_id = await primary_adapter.send_message(session_id, text, metadata)

        # Broadcast to secondary adapters (feedback only - don't redistribute)
        for adapter_type, adapter in self.adapters.items():
            if adapter_type != primary_adapter_type:
                try:
                    feedback_metadata = {**(metadata or {}), "feedback_only": True}
                    await adapter.send_message(session_id, text, feedback_metadata)
                    logger.debug(
                        "Sent feedback message to %s adapter for session %s",
                        adapter_type,
                        session_id[:8],
                    )
                except Exception as e:
                    logger.warning("Failed to send feedback to %s: %s", adapter_type, e)

        return message_id

    async def discover_peers(self) -> List[Dict[str, Any]]:
        """Discover peers from all registered adapters.

        Aggregates peer lists from all adapters and deduplicates by name.
        First occurrence wins (primary adapter's data takes precedence).

        Returns:
            List of peer dicts with:
            - name: Computer name
            - status: "online" or "offline"
            - last_seen: datetime object
            - last_seen_ago: Human-readable string (e.g., "30s ago")
            - adapter_type: Which adapter discovered this peer
        """
        all_peers = []

        # Collect peers from all adapters
        for adapter_type, adapter in self.adapters.items():
            try:
                peers = await adapter.discover_peers()
                all_peers.extend(peers)
                logger.debug("Discovered %d peers from %s adapter", len(peers), adapter_type)
            except Exception as e:
                logger.error("Failed to discover peers from %s: %s", adapter_type, e)

        # Deduplicate by name (keep first occurrence = primary adapter wins)
        seen = set()
        unique_peers = []
        for peer in all_peers:
            peer_name = peer.get("name")
            if peer_name and peer_name not in seen:
                seen.add(peer_name)
                unique_peers.append(peer)

        logger.debug("Total discovered peers (deduplicated): %d", len(unique_peers))
        return unique_peers
