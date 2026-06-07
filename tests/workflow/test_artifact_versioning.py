"""Functional tests bound to the workflow artifact-versioning spec."""

from __future__ import annotations

import sys

import pytest
from fastapi import HTTPException

from teleclaude.api.todo_routes import write_artifact
from teleclaude.cli.telec import main
from teleclaude.cli.telec.handlers import todo as todo_handler
from teleclaude.constants import ARTIFACT_BUG

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/artifact-versioning"


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV7")
async def test_api_refuses_retired_bug_artifact_writes(snapshot: object) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await write_artifact(
            slug="my-bug",
            name=ARTIFACT_BUG,
            content="# Bug content",
            cwd="/path-not-used-before-validation",
        )

    exc = exc_info.value
    assert {"status_code": exc.status_code, "detail": exc.detail} == snapshot


@pytest.mark.spec(_SPEC, "UC-WAV8")
def test_cli_refuses_retired_bug_artifact_writes_before_api_call(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    snapshot: object,
) -> None:
    def fail_tool_api_request(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("workflow API should not be called for retired artifact writes")

    monkeypatch.setattr(sys, "argv", ["telec", "todo", "artifacts", "write", "my-bug", ARTIFACT_BUG, "# Bug"])
    monkeypatch.setattr(todo_handler, "tool_api_request", fail_tool_api_request)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert {"stdout": captured.out, "stderr": captured.err} == snapshot
