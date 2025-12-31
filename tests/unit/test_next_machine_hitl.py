from unittest.mock import MagicMock, patch

import pytest

from teleclaude.core.db import Db
from teleclaude.core.next_machine import next_prepare


@pytest.mark.asyncio
async def test_next_prepare_hitl_no_slug():
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"

    with patch("teleclaude.core.next_machine.resolve_slug", return_value=(None, False, "")):
        result = await next_prepare(db, slug=None, cwd=cwd, hitl=True)
        assert "Read todos/roadmap.md" in result
        assert "Before proceeding, read ~/.agents/commands/next-prepare.md" in result


@pytest.mark.asyncio
async def test_next_prepare_hitl_missing_requirements():
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    with patch("teleclaude.core.next_machine.check_file_exists", return_value=False):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=True)
        assert f"Preparing: {slug}" in result
        assert "Write todos/test-slug/requirements.md" in result
        assert "Before proceeding, read ~/.agents/commands/next-prepare.md" in result


@pytest.mark.asyncio
async def test_next_prepare_hitl_missing_impl_plan():
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    def mock_check_file_exists(path_cwd, relative_path):
        if "requirements.md" in relative_path:
            return True
        return False

    with patch("teleclaude.core.next_machine.check_file_exists", side_effect=mock_check_file_exists):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=True)
        assert f"Preparing: {slug}" in result
        assert "Write todos/test-slug/implementation-plan.md" in result
        assert "Before proceeding, read ~/.agents/commands/next-prepare.md" in result


@pytest.mark.asyncio
async def test_next_prepare_hitl_both_exist():
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    with patch("teleclaude.core.next_machine.check_file_exists", return_value=True):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=True)
        assert f"PREPARED: todos/{slug} is ready for work." in result


@pytest.mark.asyncio
async def test_next_prepare_autonomous_dispatch():
    db = MagicMock(spec=Db)
    cwd = "/tmp/test"
    slug = "test-slug"

    # Mock agent availability
    db.clear_expired_agent_availability.return_value = None
    db.get_agent_availability.return_value = {"available": True}

    with patch("teleclaude.core.next_machine.check_file_exists", return_value=False):
        result = await next_prepare(db, slug=slug, cwd=cwd, hitl=False)
        assert "teleclaude__run_agent_command" in result
        assert f'args="{slug}"' in result
        assert 'command="next-prepare"' in result
