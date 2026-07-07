"""Z-owned preservation tests for adapter-refactor relocation gaps."""

from __future__ import annotations

import pytest

from teleclaude.core.identity import IdentityContext
from teleclaude.core.models import Session
from tests.agent_runtime.test_inbound_resolve_or_create import (
    _DiscordGuildHarness,
    _GuildAuthor,
    _GuildChannel,
    _GuildMessage,
    _GuildRef,
    _install_discord_fakes,
)

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SECOND_INBOUND_TEXT = "second inbound message"


async def test_existing_initializing_discord_session_accepts_inbound_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """Existing initializing sessions dispatch inbound text; only is_new skips bundled first delivery."""
    identity = IdentityContext(person_name="Alex", person_slug="alex", person_role="member")
    fake_db, service = _install_discord_fakes(monkeypatch, identity=identity)

    user_id = "222"
    channel_id = 4242
    existing_session = Session(
        session_id="initializing-thread-session",
        computer_name="local",
        tmux_session_name="initializing-thread-session",
        title="Project thread",
        lifecycle_status="initializing",
        origin_metadata={"discord": {"user_id": user_id, "channel_id": channel_id, "guild_id": None}},
    )
    fake_db.sessions[existing_session.session_id] = existing_session

    harness = _DiscordGuildHarness(project_path=str(tmp_path))
    message = _GuildMessage(
        author=_GuildAuthor(id=int(user_id)),
        channel=_GuildChannel(channel_id),
        guild=_GuildRef(id=42),
        content=_SECOND_INBOUND_TEXT,
    )

    await harness._handle_on_message(message)

    assert len(service.create_calls) == 0
    assert len(service.process_calls) == 1
    delivered = service.process_calls[0]
    assert delivered.session_id == existing_session.session_id
    assert delivered.text == _SECOND_INBOUND_TEXT
