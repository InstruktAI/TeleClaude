"""Snapshot coverage for Gemini runner command assembly."""

from __future__ import annotations

import json
import subprocess
from typing import Any, TypedDict

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.helpers import agent_cli
from teleclaude.helpers.agent_types import AgentName, ThinkingMode

pytestmark = pytest.mark.unit


class _OneshotCapture(TypedDict, total=False):
    cmd_parts: list[str]
    stdin: str | None


class _JobCapture(TypedDict, total=False):
    cmd_parts: list[str]
    job_role: str | None


def test_gemini_oneshot_command_flags(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    captured: _OneshotCapture = {}

    def fake_run(cmd_parts: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["cmd_parts"] = cmd_parts
        captured["stdin"] = kwargs.get("input")
        return subprocess.CompletedProcess(
            cmd_parts,
            0,
            stdout=json.dumps({"response": '{"answer":"ok"}'}),
            stderr="",
        )

    monkeypatch.setattr(agent_cli, "_pick_agent", lambda _preferred: AgentName.GEMINI)
    monkeypatch.setattr(agent_cli, "resolve_agent_binary", lambda _agent: "gemini")
    monkeypatch.setattr(agent_cli.subprocess, "run", fake_run)

    payload = agent_cli.run_once(
        agent="gemini",
        thinking_mode=ThinkingMode.FAST.value,
        system="system",
        prompt="prompt",
        schema={"type": "object"},
        tools="web_search",
        input_mode="arg",
    )

    assert {"captured": captured, "payload": payload} == snapshot


def test_gemini_job_command_flags(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    captured: _JobCapture = {}

    def fake_run(cmd_parts: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        env = kwargs.get("env")
        captured["cmd_parts"] = cmd_parts
        job_role = env.get("TELECLAUDE_JOB_ROLE") if isinstance(env, dict) else None
        captured["job_role"] = job_role if isinstance(job_role, str) else None
        return subprocess.CompletedProcess(cmd_parts, 0)

    monkeypatch.setattr(agent_cli, "_pick_agent", lambda _preferred: AgentName.GEMINI)
    monkeypatch.setattr(agent_cli, "resolve_agent_binary", lambda _agent: "gemini")
    monkeypatch.setattr(agent_cli.subprocess, "run", fake_run)

    return_code = agent_cli.run_job(
        agent="gemini",
        thinking_mode=ThinkingMode.FAST.value,
        prompt="job prompt",
    )

    assert {"captured": captured, "return_code": return_code} == snapshot
