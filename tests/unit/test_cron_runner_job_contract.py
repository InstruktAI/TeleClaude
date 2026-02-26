import pytest
from typing_extensions import TypedDict

from teleclaude.config.schema import JobScheduleConfig
from teleclaude.cron.runner import _build_agent_job_message, _job_slug_to_spec_filename, _run_agent_job


class _CreateSessionCapture(TypedDict, total=False):
    agent: str | None
    thinking_mode: str


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


@pytest.mark.unit
def test_run_agent_job_omits_explicit_agent_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: _CreateSessionCapture = {}

    class FakeAPIClient:
        async def connect(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def create_session(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return {"status": "success"}

    monkeypatch.setattr("teleclaude.cli.api_client.TelecAPIClient", FakeAPIClient)

    ok = _run_agent_job("memory_review", JobScheduleConfig(type="agent", job="memory-review", thinking_mode="fast"))

    assert ok is True
    assert captured["agent"] is None
    assert captured["thinking_mode"] == "fast"


@pytest.mark.unit
def test_run_agent_job_preserves_explicit_agent_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: _CreateSessionCapture = {}

    class FakeAPIClient:
        async def connect(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def create_session(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return {"status": "success"}

    monkeypatch.setattr("teleclaude.cli.api_client.TelecAPIClient", FakeAPIClient)

    ok = _run_agent_job(
        "memory_review",
        JobScheduleConfig(type="agent", job="memory-review", agent="gemini", thinking_mode="med"),
    )

    assert ok is True
    assert captured["agent"] == "gemini"
    assert captured["thinking_mode"] == "med"
