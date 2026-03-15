from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from teleclaude.adapters.discord.provisioning import ProvisioningMixin

pytestmark = pytest.mark.unit


class DummyProvisioning(ProvisioningMixin):
    def __init__(self) -> None:
        self._guild_id = 123
        self._require_async_callable = lambda fn, *, label: fn
        self._client = SimpleNamespace(
            get_guild=lambda guild_id: None, fetch_guild=AsyncMock(return_value="fetched-guild")
        )


@pytest.mark.asyncio
async def test_resolve_guild_prefers_cached_guild_before_fetching() -> None:
    adapter = DummyProvisioning()
    adapter._client = SimpleNamespace(
        get_guild=lambda guild_id: "cached-guild",
        fetch_guild=AsyncMock(return_value="fetched-guild"),
    )

    result = await adapter._resolve_guild()

    assert result == "cached-guild"
    adapter._client.fetch_guild.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_guild_fetches_when_cache_misses_and_returns_none_on_failure() -> None:
    adapter = DummyProvisioning()

    assert await adapter._resolve_guild() == "fetched-guild"
    adapter._client.fetch_guild.assert_awaited_once_with(123)

    adapter._client = SimpleNamespace(
        get_guild=lambda guild_id: None,
        fetch_guild=AsyncMock(side_effect=RuntimeError("boom")),
    )

    assert await adapter._resolve_guild() is None


def test_persist_discord_channel_ids_merges_categories_and_scalar_fields(tmp_path: Path) -> None:
    adapter = DummyProvisioning()
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "discord": {
                    "categories": {"existing": 1},
                    "help_desk_channel_id": 2,
                }
            }
        ),
        encoding="utf-8",
    )

    with patch("teleclaude.config.config_path", config_path):
        adapter._persist_discord_channel_ids({"categories": {"new": 3}, "all_sessions_channel_id": 4})

    persisted = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert persisted["discord"] == {
        "categories": {"existing": 1, "new": 3},
        "help_desk_channel_id": 2,
        "all_sessions_channel_id": 4,
    }


def test_persist_project_forum_ids_updates_named_trusted_dirs_and_removes_none(tmp_path: Path) -> None:
    adapter = DummyProvisioning()
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "computer": {
                    "trusted_dirs": [
                        {"name": "a", "path": "/a", "discord_forum": 10},
                        {"name": "b", "path": "/b", "discord_forum": 20},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    with patch("teleclaude.config.config_path", config_path):
        adapter._persist_project_forum_ids([("a", 11), ("b", None)])

    trusted_dirs = yaml.safe_load(config_path.read_text(encoding="utf-8"))["computer"]["trusted_dirs"]

    assert trusted_dirs == [
        {"name": "a", "path": "/a", "discord_forum": 11},
        {"name": "b", "path": "/b"},
    ]
