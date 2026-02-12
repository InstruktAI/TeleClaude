import pytest

from teleclaude.config.schema import JobScheduleConfig
from teleclaude.cron.runner import _build_agent_job_message, _job_slug_to_spec_filename


@pytest.mark.unit
def test_build_agent_job_message_requires_job_field() -> None:
    assert _build_agent_job_message("memory_review", JobScheduleConfig(type="agent", job=None)) is None


@pytest.mark.unit
def test_build_agent_job_message_rejects_message_field() -> None:
    assert (
        _build_agent_job_message("memory_review", JobScheduleConfig(type="agent", message="legacy", job="job")) is None
    )


@pytest.mark.unit
def test_build_agent_job_message_uses_job_slug() -> None:
    msg = _build_agent_job_message("memory_review", JobScheduleConfig(type="agent", job="memory-review"))
    assert msg is not None
    assert "memory_review job" in msg
    assert _job_slug_to_spec_filename("memory-review") in msg
