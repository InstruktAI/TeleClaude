"""Assemble the conversation's parts for one daemon: the capturer on every computer, the poster for when it is master.

Every computer runs the capturer for the sessions it hosts and the courier that passes limit responses to the master.
Every computer also holds a poster, because which computer is the master is the fleet's to decide and can change;
a poster that is not on the master refuses everything with that cause, and the budget admits nothing from it.
"""

from __future__ import annotations

import asyncio

from teleclaude.core.db import db
from teleclaude.core.workflow_store.github_conversation import ConversationPublisher
from teleclaude.core.workflow_store.github_conversation_budget import ConversationBudget, MasterTenure
from teleclaude.core.workflow_store.github_conversation_budget_store import ConversationBudgetStore
from teleclaude.core.workflow_store.github_conversation_limits import LimitNoticeCourier
from teleclaude.core.workflow_store.github_conversation_master import (
    ConversationMasterLink,
    register_conversation_poster,
)
from teleclaude.core.workflow_store.github_conversation_poster import GitHubConversationPoster


class ConversationRuntime:
    """The conversation's long-lived objects for this daemon, started and stopped with it."""

    def __init__(self) -> None:
        self._store = ConversationBudgetStore(db.open_session)
        self._link = ConversationMasterLink()
        tenure = MasterTenure(db.get_system_setting, db.set_system_setting)
        self._poster = GitHubConversationPoster(ConversationBudget(self._store, tenure))
        self._courier: LimitNoticeCourier | None = None
        self.publisher = ConversationPublisher(self._link, tenure, self._deliver_notices)

    async def _deliver_notices(self) -> None:
        if self._courier is not None:
            await self._courier.deliver()

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Begin answering conversation requests and passing limit responses to the master."""
        self._courier = LimitNoticeCourier(self._store, self._link, loop)
        self._courier.install()
        register_conversation_poster(self._poster)

    def stop(self) -> None:
        """Stop answering conversation requests and observing limit responses."""
        register_conversation_poster(None)
        if self._courier is not None:
            self._courier.uninstall()
            self._courier = None
