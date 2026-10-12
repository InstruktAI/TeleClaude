"""Help desk categories: one private Discord category per hosted desk, reconciled by the master.

Every desk the master hosts gets a category holding a customer-sessions forum, an
escalations forum and a team-chat channel. Visibility and abilities are per-person
permission overwrites computed from the desk's scope, which identity resolves. The
master alone creates, re-syncs and removes these artifacts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord.provisioning import ProvisioningMixin
from teleclaude.adapters.discord.team_channels import base_private_overwrites
from teleclaude.config.loader import load_global_config, load_person_config_for_entry
from teleclaude.core.db import db
from teleclaude.core.endpoints import DeskIdentifier, hosted_desks
from teleclaude.core.integration.discord_admin_state import (
    DiscordArtifactKind,
    DiscordProvider,
    DiscordReflectionRecord,
    DiscordReflectionScope,
    DiscordScopeKind,
    HelpDeskArtifact,
    help_desk_key,
    parse_help_desk_key,
)
from teleclaude.core.organization import desk_scope
from teleclaude.paths import PEOPLE_DIR

if TYPE_CHECKING:
    from types import ModuleType

logger = get_logger(__name__)

_DISCORD_CATEGORY_TYPE = 4
_DISCORD_TEXT_TYPE = 0
_DESK_IDENTIFIER_PREFIX = "hd-"
_CATEGORY_NAME_TEMPLATE = "Help Desk - {desk}"
_CUSTOMER_SESSIONS_TOPIC = "Customer sessions of this help desk"
_ESCALATIONS_TOPIC = "Escalations of this help desk"
_FETCH_CHANNELS_LABEL = "guild.fetch_channels"
_FETCH_MEMBER_LABEL = "guild.fetch_member"
_DELETE_LABEL = "help desk channel delete"
_EDIT_LABEL = "help desk channel edit overwrites"
_NOT_FOUND_ATTR = "NotFound"
_OVERWRITES_ATTR = "overwrites"
_PAIR_ATTR = "pair"
_ID_ATTR = "id"
_VALUE_ATTR = "value"
_EDIT_ATTR = "edit"
_DELETE_ATTR = "delete"
_FETCH_CHANNELS_ATTR = "fetch_channels"
_FETCH_MEMBER_ATTR = "fetch_member"
_GUILD_UNAVAILABLE_MESSAGE = "The configured guild could not be resolved."
_AMBIGUOUS_CATEGORY_MESSAGE = "Multiple Discord categories match help desk {desk}."
_MISSING_CATEGORY_MESSAGE = "Required Discord category for help desk {desk} could not be resolved or created."
_AMBIGUOUS_CHANNEL_MESSAGE = "Multiple Discord channels match help desk {desk} artifact {artifact}."
_MISSING_CHANNEL_MESSAGE = (
    "Required Discord channel for help desk {desk} artifact {artifact} could not be resolved or created."
)
_OBJECT_ATTR = "Object"
_PERMISSION_OVERWRITE_ATTR = "PermissionOverwrite"
_SHARED_SCOPE_VALUE = "shared"
_EMPTY_METADATA_JSON = "{}"
_OVERWRITES_EDITED_EVENT = "discord.help_desk_overwrites.edited"
_REMOVAL_COMPLETED_EVENT = "discord.help_desk_removal.completed"
_RETIREMENT_COMPLETED_EVENT = "discord.shared_help_desk_retirement.completed"
_LEGACY_CATEGORY_KEY = "discord.categories.help_desk"
_LEGACY_CHANNEL_KEYS = (
    "discord.help_desk_channel_id",
    "discord.escalation_channel_id",
    "discord.operator_chat_channel_id",
)
_LEGACY_CATEGORY_NAME = "Help Desk"

# What the bot holds on every desk artifact beyond view, read, send and message management.
_BOT_THREAD_PERMISSIONS: dict[str, bool] = {
    "read_message_history": True,
    "send_messages_in_threads": True,
    "create_public_threads": True,
    "manage_threads": True,
}

# What a person in the desk's scope holds on each artifact; everything else is denied by @everyone.
_MEMBER_ABILITIES: dict[HelpDeskArtifact, dict[str, bool]] = {
    HelpDeskArtifact.CATEGORY: {"view_channel": True},
    HelpDeskArtifact.CUSTOMER_SESSIONS: {
        "view_channel": True,
        "read_message_history": True,
        "send_messages": False,
        "send_messages_in_threads": False,
        "create_public_threads": False,
        "create_private_threads": False,
    },
    HelpDeskArtifact.ESCALATIONS: {
        "view_channel": True,
        "read_message_history": True,
        "send_messages_in_threads": True,
        "send_messages": False,
        "create_public_threads": False,
        "create_private_threads": False,
    },
    HelpDeskArtifact.TEAM_CHAT: {
        "view_channel": True,
        "read_message_history": True,
        "send_messages": True,
    },
}

_CHANNEL_NAMES: dict[HelpDeskArtifact, str] = {
    HelpDeskArtifact.CUSTOMER_SESSIONS: "customer-sessions",
    HelpDeskArtifact.ESCALATIONS: "escalations",
    HelpDeskArtifact.TEAM_CHAT: "team-chat",
}

# Children are removed before their category.
_REMOVAL_ORDER = (
    HelpDeskArtifact.TEAM_CHAT,
    HelpDeskArtifact.ESCALATIONS,
    HelpDeskArtifact.CUSTOMER_SESSIONS,
    HelpDeskArtifact.CATEGORY,
)


@dataclass(frozen=True)
class DeskForums:
    """The forums of one provisioned desk that sessions and the stale-thread sweep address."""

    customer_sessions: int | None
    escalations: int | None


class _Lookup(StrEnum):
    """What searching the guild listing for one desk artifact established."""

    FOUND = "found"
    ABSENT = "absent"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class _Resolution:
    """The outcome of resolving one desk artifact against the guild listing."""

    lookup: _Lookup
    channel_id: int | None = None


class _PassCache:
    """Facts read once per reconciliation pass and shared by every desk in it."""

    def __init__(self) -> None:
        self.user_ids: dict[str, int | None] = {}
        self.membership: dict[int, bool] = {}


def _channel_type_value(channel: object) -> object:
    channel_type = getattr(channel, "type", None)
    return getattr(channel_type, "value", channel_type)


def _overwrite_signature(overwrites: Mapping[object, object]) -> dict[int, tuple[int, int]]:
    """Reduce overwrites to what Discord enforces: allowed and denied permission bits per target id."""
    signature: dict[int, tuple[int, int]] = {}
    for target, overwrite in overwrites.items():
        allow, deny = getattr(overwrite, _PAIR_ATTR)()
        signature[getattr(target, _ID_ATTR)] = (getattr(allow, _VALUE_ATTR), getattr(deny, _VALUE_ATTR))
    return signature


class HelpDeskCategoriesMixin(ProvisioningMixin):
    """Mixin providing per-desk Discord categories for DiscordAdapter.

    Required host attributes:
    - _client: DiscordClientLike | None
    - _discord: ModuleType
    """

    _desk_forums: dict[str, DeskForums]

    if TYPE_CHECKING:
        _discord: ModuleType

    async def _reconcile_help_desk_categories(self) -> None:
        """Bring the guild's desk categories in step with the desks this computer hosts.

        One pass reads the hosted desks and every desk's scope in full, so a change
        that arrives during a pass is absorbed by the next. Desk, scope, binding and
        Discord answers are trusted as given; an error from any of them fails the
        pass with that error.
        """
        if self._client is None or self._guild_id is None or not await self._holds_shared_provider_authority():
            return
        hosted = hosted_desks(is_master=True)
        guild = await self._resolve_guild()
        if guild is None:
            raise AdapterError(_GUILD_UNAVAILABLE_MESSAGE)
        listing = await self._list_guild_channels(guild)
        cache = _PassCache()
        for desk in hosted:
            await self._reconcile_desk(guild, listing, desk, cache)
        await self._remove_unhosted_desks(listing, frozenset(desk.render() for desk in hosted))
        await self._refresh_desk_forums()

    # -- Structure ----------------------------------------------------------

    async def _list_guild_channels(self, guild: object) -> dict[int, object]:
        """Every channel of the guild by id from Discord's REST listing."""
        fetch_channels = self._require_async_callable(getattr(guild, _FETCH_CHANNELS_ATTR), label=_FETCH_CHANNELS_LABEL)
        channels: dict[int, object] = {}
        for channel in cast("Iterable[object]", await fetch_channels()):
            channel_id = self._parse_optional_int(getattr(channel, "id", None))
            if channel_id is not None:
                channels[channel_id] = channel
        return channels

    def _is_artifact_kind(self, channel: object, artifact: HelpDeskArtifact) -> bool:
        if artifact is HelpDeskArtifact.CATEGORY:
            return _channel_type_value(channel) == _DISCORD_CATEGORY_TYPE
        if artifact is HelpDeskArtifact.TEAM_CHAT:
            return _channel_type_value(channel) == _DISCORD_TEXT_TYPE
        return self._is_forum_channel(channel)

    async def _resolve_artifact(
        self,
        listing: Mapping[int, object],
        entry_identifier: str,
        artifact: HelpDeskArtifact,
        category: object | None,
        name: str,
    ) -> _Resolution:
        """Find one desk artifact in the guild listing: the recorded one, else exactly one same-named in place."""

        def in_place(channel: object) -> bool:
            if not self._is_artifact_kind(channel, artifact):
                return False
            return category is None or self._channel_matches_category(channel, category)

        record = await db.get_discord_reflection(help_desk_key(entry_identifier, artifact))
        if record is not None:
            recorded = listing.get(record.provider_id)
            if recorded is not None and in_place(recorded):
                return _Resolution(_Lookup.FOUND, record.provider_id)
        candidates = [
            channel_id
            for channel_id, channel in listing.items()
            if in_place(channel) and str(getattr(channel, "name", "")).lower() == name.lower()
        ]
        if len(candidates) > 1:
            return _Resolution(_Lookup.AMBIGUOUS)
        if candidates:
            return _Resolution(_Lookup.FOUND, candidates[0])
        return _Resolution(_Lookup.ABSENT)

    def _desk_base_overwrites(self, guild: object) -> dict[object, object]:
        bot_user = getattr(self._client, "user", None) if self._client is not None else None
        return base_private_overwrites(self._discord, guild, bot_user, **_BOT_THREAD_PERMISSIONS)

    async def _record_desk_artifact(
        self, entry_identifier: str, artifact: HelpDeskArtifact, channel_id: int, parent_id: int | None
    ) -> None:
        kind = {
            HelpDeskArtifact.CATEGORY: DiscordArtifactKind.CATEGORY,
            HelpDeskArtifact.TEAM_CHAT: DiscordArtifactKind.TEXT_CHANNEL,
        }.get(artifact, DiscordArtifactKind.FORUM)
        await db.upsert_discord_reflection(
            DiscordReflectionRecord(
                provider=DiscordProvider.DISCORD,
                logical_key=help_desk_key(entry_identifier, artifact),
                artifact_kind=kind,
                scope=DiscordReflectionScope(kind=DiscordScopeKind.SHARED, value=_SHARED_SCOPE_VALUE),
                provider_id=channel_id,
                parent_provider_id=parent_id,
                metadata_json=_EMPTY_METADATA_JSON,
                verified_at=datetime.now(UTC),
            )
        )

    async def _ensure_desk_category(self, guild: object, listing: Mapping[int, object], desk: DeskIdentifier) -> object:
        """The desk's category: the recorded or the single same-named one, else a new closed one."""
        entry_identifier = desk.render()
        name = _CATEGORY_NAME_TEMPLATE.format(desk=entry_identifier.removeprefix(_DESK_IDENTIFIER_PREFIX))
        resolution = await self._resolve_artifact(listing, entry_identifier, HelpDeskArtifact.CATEGORY, None, name)
        if resolution.lookup is _Lookup.AMBIGUOUS:
            raise AdapterError(_AMBIGUOUS_CATEGORY_MESSAGE.format(desk=entry_identifier))
        if resolution.channel_id is not None:
            category = listing.get(resolution.channel_id)
        else:
            category = await self._find_or_create_category(
                guild,
                name,
                overwrites=self._desk_base_overwrites(guild),
                propagate_errors=True,
            )
        category_id = self._parse_optional_int(getattr(category, "id", None))
        if category is None or category_id is None:
            raise AdapterError(_MISSING_CATEGORY_MESSAGE.format(desk=entry_identifier))
        await self._record_desk_artifact(entry_identifier, HelpDeskArtifact.CATEGORY, category_id, None)
        return category

    async def _ensure_desk_channel(
        self,
        guild: object,
        listing: Mapping[int, object],
        desk: DeskIdentifier,
        category: object,
        artifact: HelpDeskArtifact,
    ) -> object:
        """One of the desk's channels: the recorded or the single same-named one in its category, else a new closed one."""
        entry_identifier = desk.render()
        name = _CHANNEL_NAMES[artifact]
        resolution = await self._resolve_artifact(listing, entry_identifier, artifact, category, name)
        if resolution.lookup is _Lookup.AMBIGUOUS:
            raise AdapterError(_AMBIGUOUS_CHANNEL_MESSAGE.format(desk=entry_identifier, artifact=artifact.value))
        channel_id = resolution.channel_id
        if channel_id is None:
            channel_id = await self._create_desk_channel(guild, category, artifact, name)
        if channel_id is None:
            raise AdapterError(_MISSING_CHANNEL_MESSAGE.format(desk=entry_identifier, artifact=artifact.value))
        channel = listing.get(channel_id) or await self._get_channel(channel_id)
        if channel is None:
            raise AdapterError(_MISSING_CHANNEL_MESSAGE.format(desk=entry_identifier, artifact=artifact.value))
        await self._record_desk_artifact(
            entry_identifier, artifact, channel_id, self._parse_optional_int(getattr(category, "id", None))
        )
        return channel

    async def _create_desk_channel(
        self, guild: object, category: object, artifact: HelpDeskArtifact, name: str
    ) -> int | None:
        overwrites = self._desk_base_overwrites(guild)
        if artifact is HelpDeskArtifact.TEAM_CHAT:
            return await self._find_or_create_text_channel(
                guild, category, name, category_scoped=True, overwrites=overwrites, propagate_errors=True
            )
        topic = _CUSTOMER_SESSIONS_TOPIC if artifact is HelpDeskArtifact.CUSTOMER_SESSIONS else _ESCALATIONS_TOPIC
        return await self._find_or_create_forum(
            guild, category, name, topic, overwrites=overwrites, propagate_errors=True
        )

    # -- Grants -------------------------------------------------------------

    async def _reconcile_desk(
        self, guild: object, listing: Mapping[int, object], desk: DeskIdentifier, cache: _PassCache
    ) -> None:
        """Ensure one desk's structure exists, then make its grants match its scope."""
        category = await self._ensure_desk_category(guild, listing, desk)
        artifacts: dict[HelpDeskArtifact, object] = {HelpDeskArtifact.CATEGORY: category}
        for artifact in _CHANNEL_NAMES:
            channel = await self._ensure_desk_channel(guild, listing, desk, category, artifact)
            artifacts[artifact] = channel
        member_ids = await self._scope_member_ids(guild, desk_scope(desk).people, cache)
        base = self._desk_base_overwrites(guild)
        for artifact, channel in artifacts.items():
            await self._sync_overwrites(
                channel, self._desired_overwrites(base, member_ids, _MEMBER_ABILITIES[artifact])
            )

    async def _scope_member_ids(self, guild: object, people: Iterable[str], cache: _PassCache) -> frozenset[int]:
        """The Discord user ids of the scope people who are bound and in the guild.

        A person with no bound account, or not in the guild, is given no grant.
        """
        member_ids: set[int] = set()
        for slug in people:
            if slug not in cache.user_ids:
                cache.user_ids[slug] = self._discord_user_id(slug)
            user_id = cache.user_ids[slug]
            if user_id is not None and await self._is_guild_member(guild, user_id, cache):
                member_ids.add(user_id)
        return frozenset(member_ids)

    def _discord_user_id(self, slug: str) -> int | None:
        """A person's bound Discord account, read from their configuration; None when they have none."""
        entry = next((person for person in load_global_config().people if person.slug == slug), None)
        if entry is None:
            return None
        person_config = load_person_config_for_entry(entry, PEOPLE_DIR)
        if person_config is None or person_config.creds.discord is None:
            return None
        return self._parse_optional_int(person_config.creds.discord.user_id)

    async def _is_guild_member(self, guild: object, user_id: int, cache: _PassCache) -> bool:
        """Whether a user is in the guild; Discord's not-found answer means they are not."""
        if user_id not in cache.membership:
            fetch_member = self._require_async_callable(getattr(guild, _FETCH_MEMBER_ATTR), label=_FETCH_MEMBER_LABEL)
            try:
                await fetch_member(user_id)
            except getattr(self._discord, _NOT_FOUND_ATTR):
                cache.membership[user_id] = False
            else:
                cache.membership[user_id] = True
        return cache.membership[user_id]

    def _desired_overwrites(
        self, base: Mapping[object, object], member_ids: frozenset[int], abilities: Mapping[str, bool]
    ) -> dict[object, object]:
        """The base entries plus one entry per scope member; no other member entry survives."""
        permission_overwrite_cls = getattr(self._discord, _PERMISSION_OVERWRITE_ATTR)
        object_cls = getattr(self._discord, _OBJECT_ATTR)
        desired = dict(base)
        for user_id in sorted(member_ids):
            desired[object_cls(id=user_id)] = permission_overwrite_cls(**abilities)
        return desired

    async def _sync_overwrites(self, channel: object, desired: Mapping[object, object]) -> None:
        """Edit a desk artifact's overwrites only where they differ from what its scope requires."""
        current = cast("Mapping[object, object]", getattr(channel, _OVERWRITES_ATTR))
        if _overwrite_signature(current) == _overwrite_signature(desired):
            return
        edit = self._require_async_callable(getattr(channel, _EDIT_ATTR), label=_EDIT_LABEL)
        await edit(overwrites=desired)
        logger.info(_OVERWRITES_EDITED_EVENT, channel_id=getattr(channel, "id", None))

    # -- Removal ------------------------------------------------------------

    async def _remove_unhosted_desks(self, listing: Mapping[int, object], hosted: frozenset[str]) -> None:
        """Delete the categories of desks no longer hosted, then their reflection records.

        A desk's records are deleted only after its Discord artifacts are gone.
        """
        records_by_entry: dict[str, dict[HelpDeskArtifact, DiscordReflectionRecord]] = {}
        for record in await db.list_discord_reflections():
            parsed = parse_help_desk_key(record.logical_key)
            if parsed is None or parsed[0] in hosted:
                continue
            records_by_entry.setdefault(parsed[0], {})[parsed[1]] = record
        for entry_identifier, records in records_by_entry.items():
            for artifact in _REMOVAL_ORDER:
                record = records.get(artifact)
                if record is not None:
                    await self._delete_listed_channel(listing, record.provider_id)
            for record in records.values():
                await db.delete_discord_reflection(record.logical_key)
            logger.info(_REMOVAL_COMPLETED_EVENT, desk=entry_identifier)

    async def _delete_listed_channel(self, listing: Mapping[int, object], channel_id: int) -> None:
        """Delete one listed channel; a channel the listing lacks, or Discord reports gone, is already deleted."""
        channel = listing.get(channel_id)
        if channel is None:
            return
        delete = self._require_async_callable(getattr(channel, _DELETE_ATTR), label=_DELETE_LABEL)
        try:
            await delete()
        except getattr(self._discord, _NOT_FOUND_ATTR):
            return

    # -- Retirement of the shared surface -----------------------------------

    async def _retire_shared_help_desk_surface(self, guild: object, *, is_master: bool) -> None:
        """Remove the guild-wide Help Desk category that per-desk categories replace.

        The master deletes the recorded children and category, and any category
        named exactly ``Help Desk``, then the legacy reflection records; a failed
        listing or delete fails the call and keeps the records, so the next start
        retries. Another computer drops only its own legacy records and never
        touches Discord.
        """
        records = [
            record
            for key in (_LEGACY_CATEGORY_KEY, *_LEGACY_CHANNEL_KEYS)
            if (record := await db.get_discord_reflection(key)) is not None
        ]
        if not is_master:
            for record in records:
                await db.delete_discord_reflection(record.logical_key)
            return
        listing = await self._list_guild_channels(guild)
        category_ids = {
            channel_id
            for channel_id, channel in listing.items()
            if _channel_type_value(channel) == _DISCORD_CATEGORY_TYPE
            and (
                getattr(channel, "name", None) == _LEGACY_CATEGORY_NAME
                or any(
                    record.logical_key == _LEGACY_CATEGORY_KEY and record.provider_id == channel_id
                    for record in records
                )
            )
        }
        recorded_child_ids = {record.provider_id for record in records if record.logical_key in _LEGACY_CHANNEL_KEYS}
        child_ids = {
            channel_id
            for channel_id, channel in listing.items()
            if channel_id in recorded_child_ids
            or self._parse_optional_int(getattr(channel, "category_id", None)) in category_ids
        }
        for channel_id in (*sorted(child_ids), *sorted(category_ids)):
            await self._delete_listed_channel(listing, channel_id)
        for record in records:
            await db.delete_discord_reflection(record.logical_key)
        if child_ids or category_ids or records:
            logger.info(_RETIREMENT_COMPLETED_EVENT, categories=sorted(category_ids), channels=sorted(child_ids))

    # -- Forum map ----------------------------------------------------------

    async def _refresh_desk_forums(self) -> None:
        """Rebuild the desk-to-forums map that session mirroring and the stale-thread sweep read."""
        ids: dict[str, dict[HelpDeskArtifact, int]] = {}
        for record in await db.list_discord_reflections():
            parsed = parse_help_desk_key(record.logical_key)
            if parsed is not None:
                ids.setdefault(parsed[0], {})[parsed[1]] = record.provider_id
        self._desk_forums = {
            entry_identifier: DeskForums(
                customer_sessions=artifacts.get(HelpDeskArtifact.CUSTOMER_SESSIONS),
                escalations=artifacts.get(HelpDeskArtifact.ESCALATIONS),
            )
            for entry_identifier, artifacts in ids.items()
        }
