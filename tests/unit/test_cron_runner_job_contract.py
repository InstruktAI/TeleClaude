import pytest

from teleclaude.cron.runner import _build_agent_job_message


@pytest.mark.unit
def test_build_agent_job_message_requires_job_field() -> None:
    assert _build_agent_job_message("memory_review", {"type": "agent"}) is None


@pytest.mark.unit
def test_build_agent_job_message_rejects_message_field() -> None:
    assert _build_agent_job_message("memory_review", {"type": "agent", "message": "legacy"}) is None


@pytest.mark.unit
def test_build_agent_job_message_uses_job_slug() -> None:
    msg = _build_agent_job_message("memory_review", {"type": "agent", "job": "memory-review"})
    assert msg is not None
    assert "@docs/project/spec/jobs/memory-review.md" in msg
