"""Hook adapter protocol for agent-specific behavior."""

from __future__ import annotations

import argparse
from typing import Protocol

from teleclaude.core.events import AgentHookEventType


class HookAdapter(Protocol):
    """Protocol for agent-specific hook behavior.

    Each adapter encapsulates the differences between agent CLIs:
    input format, field names, checkpoint responses, and memory injection.
    """

    agent_name: str
    mint_events: frozenset[AgentHookEventType]
    supports_hook_checkpoint: bool

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, dict[str, object]]:  # guard: loose-dict
        """Parse agent-specific input into (raw_input, raw_event_type, raw_data).

        Raises ValueError or json.JSONDecodeError on invalid input.
        """
        ...

    def normalize_payload(self, data: dict[str, object]) -> dict[str, object]:  # guard: loose-dict
        """Normalize agent-specific field names to canonical internal names.

        After normalization, data uses: session_id, transcript_path, prompt, message.
        """
        ...

    def format_checkpoint_response(self, reason: str) -> str | None:
        """Format checkpoint blocking response, or None if unsupported."""
        ...

    def format_memory_injection(self, context: str) -> str:
        """Format memory context for SessionStart stdout injection."""
        ...
