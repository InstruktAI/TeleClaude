"""Argument parsing shared by hook receiver entry points."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from teleclaude.agent_registry import AGENT_REGISTRY, AgentName

RECEIVER_AGENT_CHOICES: tuple[str, ...] = AgentName.choices() + tuple(
    alias for name in AgentName for alias in AGENT_REGISTRY[name].aliases
)


def build_receiver_arg_parser() -> argparse.ArgumentParser:
    """Build the hook receiver CLI parser without importing runtime config."""
    parser = argparse.ArgumentParser(description="TeleClaude hook receiver")
    parser.add_argument(
        "--agent",
        required=True,
        choices=RECEIVER_AGENT_CHOICES,
        help="Agent name for adapter selection",
    )
    parser.add_argument(
        "--cwd",
        default=None,
        help="Caller working directory for headless session attribution",
    )
    parser.add_argument("event_type", nargs="?", default=None, help="Hook event type")
    return parser


def parse_receiver_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse hook receiver CLI arguments."""
    return build_receiver_arg_parser().parse_args(argv)
