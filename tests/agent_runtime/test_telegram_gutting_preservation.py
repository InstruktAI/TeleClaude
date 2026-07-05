"""Zero-regression preservation checks for telegram-dead-code-gutting.

Pins the two KEEP paths the dead-code removal must not disturb:
send_general_message's routing to the bot, and ensure_channel's
customer-role provisioning skip.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest

from teleclaude.adapters.telegram.message_ops import EditContext, MessageOperationsMixin
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.core.models import Session

if TYPE_CHECKING:
    from telegram.ext import ExtBot

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SUPERGROUP_ID = 123456
_SENT_MESSAGE_ID = 999
_SENT_TEXT = "hello general topic"


class _MessageOpsHarness(MessageOperationsMixin):
    """Minimal host exposing only what send_general_message touches."""

    def __init__(self, bot: object, supergroup_id: int) -> None:
        self._bot = bot
        self.supergroup_id = supergroup_id
        self._pending_edits: dict[str, EditContext] = {}
        self._last_edit_hash: dict[str, str] = {}

    @property
    def bot(self) -> ExtBot[None]:
        return cast("ExtBot[None]", self._bot)

    def _ensure_started(self) -> None:
        return


class _NoProvisioningHost:
    """Sentinel host with no channel-provisioning capability.

    Any attribute access proves ensure_channel's customer-skip guard failed
    to short-circuit before touching provisioning.
    """

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"ensure_channel touched host.{name}; customer-skip guard did not short-circuit")


async def test_send_general_message_reaches_bot_send_message_and_returns_id() -> None:
    sent_message = SimpleNamespace(message_id=_SENT_MESSAGE_ID)
    send_message_mock = AsyncMock(return_value=sent_message)
    harness = _MessageOpsHarness(bot=SimpleNamespace(send_message=send_message_mock), supergroup_id=_SUPERGROUP_ID)

    result = await harness.send_general_message(_SENT_TEXT)

    assert result == str(_SENT_MESSAGE_ID)
    send_message_mock.assert_awaited_once()
    call_kwargs = send_message_mock.call_args.kwargs
    assert call_kwargs["chat_id"] == _SUPERGROUP_ID
    assert call_kwargs["text"] == _SENT_TEXT


async def test_ensure_channel_skips_provisioning_for_customer_role_session() -> None:
    session = Session(
        session_id="customer-session",
        computer_name="local",
        tmux_session_name="tmux-customer",
        title="customer",
        human_role="customer",
    )

    result = await TelegramAdapter.ensure_channel(_NoProvisioningHost(), session)

    assert result is session
