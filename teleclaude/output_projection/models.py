"""Canonical output projection models for the shared output route."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True)
class VisibilityPolicy:
    """Canonical visibility policy for output projection.

    Controls which block types are emitted by the projector.
    All consumers use a policy instance rather than scattered boolean flags.
    """

    include_tools: bool = False  # tool_use blocks
    include_tool_results: bool = False  # tool_result blocks
    include_thinking: bool = False  # thinking/reasoning blocks
    visible_tool_names: frozenset[str] = field(default_factory=frozenset)
    """Tool names that are always emitted regardless of include_tools.

    Use this to allowlist explicitly user-visible tools/widgets that should
    surface in web chat even when include_tools is False.
    """


# Canonical web policy: tools and thinking hidden by default.
# This is the correct policy for both web history and web live SSE.
WEB_POLICY = VisibilityPolicy(
    include_tools=False,
    include_tool_results=False,
    include_thinking=False,
)

# Threaded clean policy: thinking and tool invocations visible, results hidden.
# Matches the hardcoded behavior of render_clean_agent_output().
THREADED_CLEAN_POLICY = VisibilityPolicy(
    include_tools=True,
    include_tool_results=False,
    include_thinking=True,
)

# Permissive policy: all blocks visible.
# Suitable for unfiltered emission paths.
PERMISSIVE_POLICY = VisibilityPolicy(
    include_tools=True,
    include_tool_results=True,
    include_thinking=True,
)


@dataclass(frozen=True)
class ProjectedBlock:
    """A single projected output block after visibility filtering.

    Carries the original block dict so downstream serializers can access
    the full block payload without re-parsing.
    """

    block_type: str  # "text", "thinking", "tool_use", "tool_result", "compaction"
    block: dict[str, JsonValue]  # original block data (for SSE/markdown serialization)
    role: str  # "assistant", "user", "system"
    timestamp: Optional[str]  # ISO 8601 entry timestamp
    entry_index: int  # position in source entry list
    file_index: int = 0  # position in chain (for multi-file sessions)


@dataclass(frozen=True)
class TerminalLiveProjection:
    """Projected terminal live output (tmux snapshot) through the canonical route.

    Wraps poller-driven output so the core push path is routed through the
    shared projection layer. The adapter-facing send_output_update() contract
    is preserved — callers pass projection.output to the adapter unchanged.
    """

    output: str  # ANSI-stripped clean terminal snapshot
