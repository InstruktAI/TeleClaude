from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teleclaude.adapters.discord.team_channels import TeamChannelsMixin

pytestmark = pytest.mark.unit


class DummyTeamChannels(TeamChannelsMixin):
    def __init__(self) -> None:
        self._discord = SimpleNamespace(
            PermissionOverwrite=lambda **kwargs: kwargs,
            Object=lambda *, id: id,
        )
        self._client = SimpleNamespace(user="bot-user")
        self._parse_optional_int = lambda value: (
            int(str(value).strip()) if value is not None and str(value).strip().isdigit() else None
        )
        self._require_async_callable = lambda fn, *, label: fn


def test_build_private_overwrites_denies_default_role_and_allows_bot_and_member() -> None:
    adapter = DummyTeamChannels()
    guild = SimpleNamespace(default_role="everyone", get_member=lambda user_id: "member-7")

    overwrites = adapter._build_private_overwrites(guild, 7)

    assert overwrites == {
        "everyone": {"view_channel": False, "read_messages": False},
        "bot-user": {
            "view_channel": True,
            "read_messages": True,
            "send_messages": True,
            "manage_messages": True,
        },
        "member-7": {
            "view_channel": True,
            "read_messages": True,
            "send_messages": True,
        },
    }


@pytest.mark.asyncio
async def test_find_or_create_private_text_channel_returns_existing_matching_text_channel_id() -> None:
    adapter = DummyTeamChannels()
    guild = SimpleNamespace(
        default_role="everyone",
        get_member=lambda user_id: None,
        channels=[SimpleNamespace(name="alice", type=SimpleNamespace(value=0), id="55")],
    )

    channel_id = await adapter._find_or_create_private_text_channel(guild, None, "alice", None)

    assert channel_id == 55


@pytest.mark.asyncio
async def test_find_or_create_private_text_channel_creates_channel_with_overwrites_and_category() -> None:
    adapter = DummyTeamChannels()
    guild = SimpleNamespace(
        default_role="everyone",
        get_member=lambda user_id: None,
        channels=[],
        create_text_channel=AsyncMock(return_value=SimpleNamespace(id="66")),
    )
    adapter._build_private_overwrites = lambda built_guild, owner_user_id: {"owner": owner_user_id}

    channel_id = await adapter._find_or_create_private_text_channel(guild, "team-category", "bob", 9)

    assert channel_id == 66
    guild.create_text_channel.assert_awaited_once_with(
        name="bob",
        overwrites={"owner": 9},
        category="team-category",
    )
