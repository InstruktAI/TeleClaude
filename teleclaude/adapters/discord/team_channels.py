"""Team channel provisioning mixin for Discord adapter.

Handles per-person private text channels under the Team category.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.discord._channel_lookup import find_existing_text_channel_id
from teleclaude.cli.config_handlers import get_person_config
from teleclaude.core.db import db
from teleclaude.core.inbound import ConversationRef
from teleclaude.core.inbound.conversation import reconcile_designated_conversation
from teleclaude.core.inbound.models import DISCORD_DM_KEY_FIELD
from teleclaude.core.origins import InputOrigin
from teleclaude.slug import normalize_slug

if TYPE_CHECKING:
    from types import ModuleType

    from teleclaude.adapters.discord.inbound_continuity import InboundContinuity

logger = get_logger(__name__)

AsyncDiscordCallable = Callable[..., Awaitable[object]]
discord_operation_exceptions: tuple[type[Exception], ...] = (AttributeError, RuntimeError, TypeError, ValueError)

try:
    from discord import DiscordException
except ImportError:
    pass
else:
    discord_operation_exceptions = (DiscordException,) + discord_operation_exceptions


def team_channel_conversation(channel_id: int) -> ConversationRef:
    """The conversation a Team channel is: shared by every computer, keyed on the channel, carrying no desk entry."""
    return ConversationRef(
        origin=InputOrigin.DISCORD,
        key_field=DISCORD_DM_KEY_FIELD,
        key=str(channel_id),
        reaches_every_computer=True,
        carries_desk_entry=False,
    )


def base_private_overwrites(
    discord_module: object, guild: object, bot_user: object | None, **bot_permissions: bool
) -> dict[object, object]:
    """The overwrites every private surface starts from: deny @everyone, allow the bot.

    The bot always holds view, read, send and message management; ``bot_permissions``
    adds the further permissions a surface needs, such as thread handling.
    """
    permission_overwrite_cls = getattr(discord_module, "PermissionOverwrite", None)
    if permission_overwrite_cls is None:
        return {}

    overwrites: dict[object, object] = {}

    default_role = getattr(guild, "default_role", None)
    if default_role is not None:
        overwrites[default_role] = permission_overwrite_cls(view_channel=False, read_messages=False)

    if bot_user is not None:
        overwrites[bot_user] = permission_overwrite_cls(
            view_channel=True, read_messages=True, send_messages=True, manage_messages=True, **bot_permissions
        )

    return overwrites


class TeamChannelsMixin:
    """Mixin providing team channel provisioning for DiscordAdapter.

    Required host attributes:
    - _client: DiscordClientLike | None
    - _discord: ModuleType
    - _team_channel_map: dict[int, str]  (channel id -> slug of the person it was provisioned for)
    - _parse_optional_int(value) -> int | None
    - _require_async_callable(fn, *, label) -> Callable
    - _get_channel(channel_id) -> object | None (async)
    """

    _team_channel_map: dict[int, str]

    if TYPE_CHECKING:
        _continuity: InboundContinuity
        _discord: ModuleType
        _client: object

        def _parse_optional_int(self, value: object) -> int | None: ...

        @staticmethod
        def _require_async_callable(fn: object, *, label: str) -> AsyncDiscordCallable: ...

        async def _get_channel(self, channel_id: int) -> object | None: ...

    async def _ensure_team_channels(
        self,
        guild: object,
        category: object | None,
        people: list[object],
        *,
        create: bool,
    ) -> None:
        """Create a private text channel per person under the Team category.

        Each channel is only visible to the person (matched by their Discord
        user ID from per-person config) and the bot. Everyone else is denied.
        ``create`` is the shared-write authority: only the unique master creates channels
        and repairs their permissions. Without it, existing channels are resolved and
        mapped, and nothing on the provider is written.
        """
        if category is None:
            return

        for person in people:
            name = getattr(person, "name", None)
            if not isinstance(name, str) or not name.strip():
                continue
            slug = getattr(person, "slug", None) or normalize_slug(name)

            # Resolve the person's Discord user ID from per-person config
            discord_user_id: int | None = None
            try:
                person_cfg = get_person_config(slug)
                if person_cfg.creds.discord:
                    discord_user_id = self._parse_optional_int(person_cfg.creds.discord.user_id)
            except (AttributeError, OSError, TypeError, ValueError) as exc:
                logger.warning("Failed to resolve Discord user_id for person %s: %s", name, exc)

            ch_id = await self._find_or_create_private_text_channel(
                guild, category, slug, discord_user_id, create=create
            )
            if ch_id is not None:
                self._team_channel_map[ch_id] = slug
                logger.info("Team channel mapped: %s -> channel_id=%d discord_user=%s", name, ch_id, discord_user_id)
            else:
                logger.warning("Team channel not found/created for person %s (slug=%s)", name, slug)
            # Ensure permissions are correct on existing channels too
            if create and ch_id is not None and discord_user_id is not None:
                await self._ensure_channel_private(ch_id, guild, discord_user_id)
        # Input a Team channel received before it was routed was left unprocessed; recover it now.
        self._continuity.request_recovery()

    async def _reconcile_team_channels(self) -> None:
        """Settle each provisioned Team channel's conversation: adoption on the master, cutover on every computer.

        Provisioning supplies the channel-to-person association that designates a channel; the core
        owns what follows from it. One channel failing to reconcile leaves the others reconciled.
        """
        for channel_id, person_slug in self._team_channel_map.items():
            try:
                await reconcile_designated_conversation(team_channel_conversation(channel_id), person_slug)
                if await db.get_conversation_binding(InputOrigin.DISCORD.value, DISCORD_DM_KEY_FIELD, str(channel_id)):
                    await self._continuity.start_cursor_at_newest(channel_id)
            # Reconciliation is best-effort at startup: its failure must not abort adapter readiness,
            # and the channel's next use reconciles it again.
            except Exception as exc:
                logger.warning("Team channel %d reconciliation failed: %s", channel_id, exc, exc_info=True)

    # guard: loose-dict-func - kwargs is a heterogeneous discord.py channel create dict;
    # a TypedDict would need discord-py types
    async def _find_or_create_private_text_channel(
        self,
        guild: object,
        category: object | None,
        name: str,
        owner_user_id: int | None,
        *,
        create: bool = True,
    ) -> int | None:
        """Find or create a text channel with private permissions.

        Denies @everyone view access, allows only the owner and the bot. When
        ``create`` is False, resolves an existing channel but never creates.
        """
        existing_channel_id = find_existing_text_channel_id(guild, name, self._parse_optional_int)
        if existing_channel_id is not None:
            return existing_channel_id

        if not create:
            return None

        # Build permission overwrites for a private channel
        overwrites = self._build_private_overwrites(guild, owner_user_id)

        create_fn = getattr(guild, "create_text_channel", None)
        if not callable(create_fn):
            return None

        try:
            create_channel = self._require_async_callable(create_fn, label="guild.create_text_channel")
            # guard: loose-dict - dynamic kwargs; category key conditionally added
            kwargs: dict[str, object] = {"name": name, "overwrites": overwrites}
            if category is not None:
                kwargs["category"] = category
            channel = await create_channel(**kwargs)
            ch_id = self._parse_optional_int(getattr(channel, "id", None))
            if ch_id is not None:
                logger.info("Created private Discord text channel: %s (id=%s)", name, ch_id)
            return ch_id
        except discord_operation_exceptions as exc:
            logger.warning("Failed to create private text channel '%s': %s", name, exc)
            return None

    def _build_private_overwrites(self, guild: object, owner_user_id: int | None) -> dict[object, object]:
        """Build Discord permission overwrites: deny @everyone, allow owner + bot."""
        permission_overwrite_cls = getattr(self._discord, "PermissionOverwrite", None)
        if permission_overwrite_cls is None:
            return {}

        bot_user = getattr(self._client, "user", None) if self._client is not None else None
        overwrites = base_private_overwrites(self._discord, guild, bot_user)

        # Allow the person
        if owner_user_id is not None:
            object_cls = getattr(self._discord, "Object", None)
            get_member = getattr(guild, "get_member", None)
            member = get_member(owner_user_id) if callable(get_member) else None
            if member is not None:
                overwrites[member] = permission_overwrite_cls(
                    view_channel=True,
                    read_messages=True,
                    send_messages=True,
                )
            elif object_cls is not None:
                # Use Object as fallback (discord.py accepts it for overwrites)
                overwrites[object_cls(id=owner_user_id)] = permission_overwrite_cls(
                    view_channel=True, read_messages=True, send_messages=True
                )

        return overwrites

    async def _ensure_channel_private(self, channel_id: int, guild: object, owner_user_id: int) -> None:
        """Verify and fix permissions on an existing team channel."""
        channel = await self._get_channel(channel_id)
        if channel is None:
            return

        default_role = getattr(guild, "default_role", None)
        if default_role is None:
            return

        overwrites = getattr(channel, "overwrites", None)
        if overwrites and default_role in overwrites:
            existing = overwrites[default_role]
            view_pair = getattr(existing, "pair", lambda: (None, None))()
            if view_pair and len(view_pair) >= 2:
                return

        # Permissions not set — apply them
        overwrites_dict = self._build_private_overwrites(guild, owner_user_id)
        edit_fn = getattr(channel, "edit", None)
        if callable(edit_fn):
            try:
                edit_channel = self._require_async_callable(edit_fn, label="channel.edit overwrites")
                await edit_channel(overwrites=overwrites_dict)
                logger.info("Applied private permissions to team channel %s", channel_id)
            except discord_operation_exceptions as exc:
                logger.warning("Failed to apply private permissions to channel %s: %s", channel_id, exc)
