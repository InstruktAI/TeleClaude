from __future__ import annotations

import pytest
from sqlmodel import select

from teleclaude.core import db_models
from teleclaude.core.db import Db

pytestmark = pytest.mark.asyncio


async def test_create_link_and_list_members_use_persisted_ordering(db: Db) -> None:
    link = await db.create_conversation_link(
        mode="direct_link",
        created_by_session_id="sess-owner",
        metadata_json='{"topic":"sync"}',
    )
    await db.upsert_conversation_link_member(
        link_id=link.link_id,
        session_id="sess-b",
        participant_name="B",
        participant_number=2,
    )
    await db.upsert_conversation_link_member(
        link_id=link.link_id,
        session_id="sess-a",
        participant_name="A",
        participant_number=1,
    )

    fetched = await db.get_conversation_link(link.link_id)
    members = await db.list_conversation_link_members(link.link_id)

    assert fetched is not None
    assert fetched.mode == "direct_link"
    assert fetched.status == "active"
    assert fetched.metadata_json == '{"topic":"sync"}'
    assert [member.session_id for member in members] == ["sess-a", "sess-b"]


async def test_active_link_queries_filter_by_member_and_mode(db: Db) -> None:
    first = await db.create_conversation_link(mode="direct_link", created_by_session_id="sess-owner")
    second = await db.create_conversation_link(mode="gathering_link", created_by_session_id="sess-owner")
    for link in (first, second):
        await db.upsert_conversation_link_member(link_id=link.link_id, session_id="sess-a")
        await db.upsert_conversation_link_member(link_id=link.link_id, session_id="sess-b")

    active_for_a = await db.get_active_links_for_session("sess-a")
    direct = await db.get_active_links_between_sessions("sess-a", "sess-b", mode="direct_link")
    first_match = await db.get_active_link_between_sessions("sess-a", "sess-b")

    assert [link.link_id for link in active_for_a] == [first.link_id, second.link_id]
    assert [link.link_id for link in direct] == [first.link_id]
    assert first_match is not None
    assert first_match.link_id == first.link_id


async def test_upsert_member_updates_existing_row_and_remove_reports_if_it_deleted_anything(db: Db) -> None:
    link = await db.create_conversation_link(mode="direct_link", created_by_session_id="sess-owner")
    await db.upsert_conversation_link_member(
        link_id=link.link_id,
        session_id="sess-a",
        participant_name="First",
        participant_number=1,
        participant_role="worker",
        computer_name="mac-1",
    )
    await db.upsert_conversation_link_member(
        link_id=link.link_id,
        session_id="sess-a",
        participant_name="Updated",
        participant_number=9,
        participant_role="reviewer",
        computer_name="mac-2",
    )

    removed = await db.remove_conversation_link_member(link_id=link.link_id, session_id="sess-a")
    removed_again = await db.remove_conversation_link_member(link_id=link.link_id, session_id="sess-a")

    async with db._session() as session:
        member = await session.get(
            db_models.ConversationLinkMemberRow,
            {"link_id": link.link_id, "session_id": "sess-a"},
        )

    assert removed is True
    assert removed_again is False
    assert member is None


async def test_setting_status_and_cleanup_close_links_and_remove_members(db: Db) -> None:
    closable = await db.create_conversation_link(mode="direct_link", created_by_session_id="sess-owner")
    cleanup_a = await db.create_conversation_link(mode="direct_link", created_by_session_id="sess-owner")
    cleanup_b = await db.create_conversation_link(mode="gathering_link", created_by_session_id="sess-owner")
    for link in (closable, cleanup_a, cleanup_b):
        await db.upsert_conversation_link_member(link_id=link.link_id, session_id="sess-a")
    await db.upsert_conversation_link_member(link_id=closable.link_id, session_id="sess-b")

    changed = await db.set_conversation_link_status(link_id=closable.link_id, status="closed")
    active_after_close = await db.get_active_links_for_session("sess-a")
    severed = await db.sever_conversation_link(closable.link_id)
    cleaned = await db.cleanup_conversation_links_for_session("sess-a")

    assert changed is True
    assert [link.link_id for link in active_after_close] == [cleanup_a.link_id, cleanup_b.link_id]
    assert severed is True
    assert cleaned == 2

    async with db._session() as session:
        closed = await session.get(db_models.ConversationLinkRow, closable.link_id)
        remaining_members = (
            await session.exec(
                select(db_models.ConversationLinkMemberRow).where(
                    db_models.ConversationLinkMemberRow.session_id == "sess-a"
                )
            )
        ).all()

    assert closed is not None
    assert closed.closed_at is not None
    assert list(remaining_members) == []
