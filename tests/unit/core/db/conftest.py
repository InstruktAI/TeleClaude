from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import pytest

from teleclaude.core.db import Db
from teleclaude.core.models import Session, SessionAdapterMetadata, SessionMetadata


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Db]:
    database = Db(str(tmp_path / "teleclaude.db"))
    await database.initialize()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def session_factory(db: Db) -> Callable[..., Awaitable[Session]]:
    async def _create(
        *,
        session_id: str = "sess-001",
        computer_name: str = "builder-mac",
        tmux_session_name: str = "tmux-001",
        last_input_origin: str = "telegram",
        title: str = "Example Session",
        adapter_metadata: SessionAdapterMetadata | None = None,
        session_metadata: SessionMetadata | None = None,
        project_path: str | None = None,
        subdir: str | None = None,
        description: str | None = None,
        working_slug: str | None = None,
        initiator_session_id: str | None = None,
        human_email: str | None = None,
        human_role: str | None = None,
        principal: str | None = None,
        lifecycle_status: str = "active",
        active_agent: str | None = None,
        thinking_mode: str | None = None,
        emit_session_started: bool = False,
    ) -> Session:
        return await db.create_session(
            computer_name=computer_name,
            tmux_session_name=tmux_session_name,
            last_input_origin=last_input_origin,
            title=title,
            adapter_metadata=adapter_metadata,
            session_metadata=session_metadata,
            project_path=project_path,
            subdir=subdir,
            description=description,
            session_id=session_id,
            working_slug=working_slug,
            initiator_session_id=initiator_session_id,
            human_email=human_email,
            human_role=human_role,
            principal=principal,
            lifecycle_status=lifecycle_status,
            active_agent=active_agent,
            thinking_mode=thinking_mode,
            emit_session_started=emit_session_started,
        )

    return _create
