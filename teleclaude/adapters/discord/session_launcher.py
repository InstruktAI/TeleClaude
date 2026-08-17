"""Discord persistent launcher view."""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import discord as discord_module

    discord = discord_module
else:
    discord = cast(Any, importlib.import_module("discord"))

LaunchCallback = Callable[[object, str, int], Awaitable[None]]


class LauncherComponentGeneration(StrEnum):
    """Discord launcher component generations understood during reconciliation."""

    LEGACY = "legacy"
    CURRENT = "v2"


class LauncherEvent(StrEnum):
    """Structured observation events for the Discord launcher boundary."""

    RECEIVED = "discord.launcher.received"
    OWNERSHIP_DECIDED = "discord.launcher.ownership_decided"
    ACKNOWLEDGEMENT_COMPLETED = "discord.launcher.acknowledgement_completed"
    COMMAND_COMPLETED = "discord.launcher.command_completed"
    RECONCILIATION_STARTED = "discord.launcher.reconciliation_started"
    REGISTRATION_COMPLETED = "discord.launcher.registration_completed"


class LauncherOwnershipOutcome(StrEnum):
    """Closed launcher ownership decisions."""

    ACCEPTED_LOCAL = "accepted_local"
    IGNORED_FOREIGN = "ignored_foreign"
    OWNERSHIP_UNRESOLVED = "ownership_unresolved"


class LauncherOwnershipReason(StrEnum):
    """Closed reasons for launcher ownership decisions."""

    SOURCE_MATCHES_LOCAL_REGISTRATION = "source_matches_local_registration"
    SOURCE_FORUM_UNRESOLVED = "source_forum_unresolved"
    SOURCE_CATEGORY_UNRESOLVED = "source_category_unresolved"
    FOREIGN_PROJECT_CATEGORY = "foreign_project_category"
    PROJECT_FORUM_UNMAPPED = "project_forum_unmapped"
    BOUND_FORUM_MISMATCH = "bound_forum_mismatch"
    MESSAGE_ID_UNRESOLVED = "message_id_unresolved"
    MESSAGE_NOT_REGISTERED = "message_not_registered"


class LauncherAcknowledgementOutcome(StrEnum):
    """Closed Discord acknowledgement outcomes."""

    SUCCESS = "success"
    FAILED = "failed"


class LauncherAcknowledgementReason(StrEnum):
    """Closed reasons for Discord acknowledgement completion."""

    RESPONSE_DEFERRED = "response_deferred"
    RESPONSE_UNAVAILABLE = "response_unavailable"
    PROVIDER_REJECTED = "provider_rejected"


class LauncherCommandOutcome(StrEnum):
    """Closed local launcher command outcomes."""

    SESSION_CREATED_LOCAL = "session_created_local"
    FAILED = "failed"


class LauncherCommandReason(StrEnum):
    """Closed reasons for local launcher command completion."""

    SESSION_CREATED = "session_created"
    SESSION_ID_UNRESOLVED = "session_id_unresolved"
    COMMAND_FAILED = "command_failed"


class LauncherRegistrationOutcome(StrEnum):
    """Closed launcher reconciliation and registration outcomes."""

    SUCCESS = "success"
    FAILED = "failed"
    OBSOLETE_LAUNCHER_REMOVED = "obsolete_launcher_removed"


class LauncherRegistrationScope(StrEnum):
    """Closed persistent component registration scopes."""

    MESSAGE = "message"


@dataclass(frozen=True, slots=True)
class LauncherComponentIdentity:
    """Parsed launcher identity used for dispatch observation and reconciliation."""

    generation: LauncherComponentGeneration
    agent_name: str


@dataclass(frozen=True, slots=True)
class LauncherInteractionSource:
    """Provider identifiers used to decide launcher ownership without acknowledgement."""

    interaction_id: int | None
    message_id: int | None
    thread_id: int | None
    forum_id: int | None
    category_id: int | None


_LEGACY_LAUNCHER_PREFIX = "launch:"
_CURRENT_LAUNCHER_PREFIX = f"teleclaude:launcher:{LauncherComponentGeneration.CURRENT}:"


def build_launcher_custom_id(agent_name: str) -> str:
    """Build the current-generation launcher identity for an agent."""
    normalized_agent_name = agent_name.strip()
    if not normalized_agent_name:
        raise ValueError("Launcher agent name must not be empty")
    return f"{_CURRENT_LAUNCHER_PREFIX}{normalized_agent_name}"


def parse_launcher_custom_id(custom_id: object) -> LauncherComponentIdentity | None:
    """Parse current and discovery-only legacy launcher component identities."""
    if not isinstance(custom_id, str):
        return None
    prefixes = (
        (LauncherComponentGeneration.CURRENT, _CURRENT_LAUNCHER_PREFIX),
        (LauncherComponentGeneration.LEGACY, _LEGACY_LAUNCHER_PREFIX),
    )
    for generation, prefix in prefixes:
        if not custom_id.startswith(prefix):
            continue
        agent_name = custom_id.removeprefix(prefix)
        if agent_name:
            return LauncherComponentIdentity(generation=generation, agent_name=agent_name)
    return None


class SessionLauncherView(discord.ui.View):
    """Persistent launcher view with one button per enabled agent."""

    def __init__(
        self,
        *,
        enabled_agents: list[str],
        on_launch: LaunchCallback,
        launcher_forum_id: int,
    ) -> None:
        super().__init__(timeout=None)
        for agent_name in enabled_agents:
            button = discord.ui.Button(  # type: ignore[var-annotated]
                label=agent_name.capitalize(),
                custom_id=build_launcher_custom_id(agent_name),
                style=discord.ButtonStyle.primary,
            )

            async def _callback(interaction: object, selected_agent: str = agent_name) -> None:
                await on_launch(interaction, selected_agent, launcher_forum_id)

            button.callback = _callback  # type: ignore[method-assign]
            self.add_item(button)
