"""Canonical output projection models for the shared output route."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from teleclaude.config.loader import resolve_person_output_visibility_settings
from teleclaude.config.schema import (
    OUTPUT_VISIBILITY_BOTH,
    OUTPUT_VISIBILITY_MOBILE,
    OUTPUT_VISIBILITY_WEB,
    OutputVisibilitySettings,
    OutputVisibilityValue,
)
from teleclaude.constants import HUMAN_ROLE_ADMIN

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class ProjectionSurface(StrEnum):
    """Projected destination family for per-recipient visibility policy."""

    MOBILE = "mobile"
    WEB = "web"


@dataclass(frozen=True)
class VisibilityPolicy:
    """Canonical visibility policy for output projection.

    Controls which block types are emitted by the projector.
    All consumers use a policy instance rather than scattered boolean flags.
    """

    include_tools: bool = False  # tool_use blocks
    include_tool_results: bool = False  # tool_result blocks
    include_thinking: bool = False  # thinking/reasoning blocks
    include_notifications: bool = True  # TeleClaude notification text blocks
    include_system_messages: bool = True  # Orchestrator/system coordination text blocks
    visible_tool_names: frozenset[str] = field(default_factory=frozenset)
    """Tool names that are always emitted regardless of include_tools.

    Use this to allowlist explicitly user-visible tools/widgets that should
    surface in web chat even when include_tools is False.
    """


def _setting_enabled(
    setting: OutputVisibilityValue | None,
    *,
    default: bool,
    surface: ProjectionSurface,
) -> bool:
    if setting is None:
        return default
    if setting == OUTPUT_VISIBILITY_BOTH:
        return True
    if setting == OUTPUT_VISIBILITY_MOBILE:
        return surface is ProjectionSurface.MOBILE
    if setting == OUTPUT_VISIBILITY_WEB:
        return surface is ProjectionSurface.WEB
    return False


def visibility_policy_for_recipient(
    *,
    human_role: str | None,
    surface: ProjectionSurface | str,
    settings: OutputVisibilitySettings | None = None,
    include_thinking: bool = False,
    visible_tool_names: frozenset[str] | None = None,
) -> VisibilityPolicy:
    """Build output visibility from recipient role, surface, and optional settings."""
    projection_surface = ProjectionSurface(surface)
    output_visibility = settings or OutputVisibilitySettings()
    is_admin = human_role == HUMAN_ROLE_ADMIN

    return VisibilityPolicy(
        include_tools=_setting_enabled(
            output_visibility.tool_calls,
            default=is_admin,
            surface=projection_surface,
        ),
        include_tool_results=False,
        include_thinking=include_thinking,
        include_notifications=_setting_enabled(
            output_visibility.notifications,
            default=False,
            surface=projection_surface,
        ),
        include_system_messages=_setting_enabled(
            output_visibility.system_messages,
            default=is_admin,
            surface=projection_surface,
        ),
        visible_tool_names=visible_tool_names or frozenset(),
    )


def visibility_policy_for_person(
    *,
    human_role: str | None,
    surface: ProjectionSurface | str,
    person_email: str | None = None,
    person_name: str | None = None,
    include_thinking: bool = False,
    visible_tool_names: frozenset[str] | None = None,
) -> VisibilityPolicy:
    """Build output visibility for a configured person recipient."""
    settings = resolve_person_output_visibility_settings(
        person_email=person_email,
        person_name=person_name,
    )
    return visibility_policy_for_recipient(
        human_role=human_role,
        surface=surface,
        settings=settings,
        include_thinking=include_thinking,
        visible_tool_names=visible_tool_names,
    )


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
    timestamp: str | None  # ISO 8601 entry timestamp
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
