"""Agent Coordinator - orchestrates agent events and cross-computer communication.

Handles agent lifecycle events (start, stop) and routes them to:
1. Local listeners (via tmux injection)
2. Remote initiators (via Redis transport)
3. Human UI (via AdapterClient feedback)
"""

from teleclaude.core.agent_coordinator._coordinator import AgentCoordinator
from teleclaude.core.agent_coordinator._helpers import SESSION_START_MESSAGES

__all__ = [
    "SESSION_START_MESSAGES",
    "AgentCoordinator",
]
