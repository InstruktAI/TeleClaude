"""Functional tests bound to the workflow todo-creation spec."""

from __future__ import annotations

import sys

import pytest

from teleclaude.cli.telec import main

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/todo-creation"


@pytest.mark.spec(_SPEC, "UC-WTC1")
def test_create_help_exposes_canonical_kind_choices(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    snapshot: object,
) -> None:
    monkeypatch.setattr(sys, "argv", ["telec", "todo", "create", "--help"])

    main()

    captured = capsys.readouterr()
    assert {"stdout": captured.out, "stderr": captured.err} == snapshot
