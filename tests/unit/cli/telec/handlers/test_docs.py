from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict

import pytest

docs = importlib.import_module("teleclaude.cli.telec.handlers.docs")


class ContextCall(TypedDict):
    areas: list[str]
    project_root: Path
    snippet_ids: list[str] | None
    baseline_only: bool
    include_third_party: bool
    domains: list[str] | None
    effective_human_role: str


def test_handle_docs_help_prints_usage(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(docs, "_usage", lambda *args: f"usage:{'/'.join(args)}")

    docs._handle_docs(["--help"])

    assert capsys.readouterr().out == "usage:docs\n"


def test_handle_docs_index_builds_context_with_filters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    received: list[ContextCall] = []

    monkeypatch.chdir(tmp_path)

    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            sys.modules,
            "teleclaude.context_selector",
            SimpleNamespace(build_context_output=lambda **kwargs: received.append(kwargs) or "INDEX"),
        )
        sys_patch.setitem(
            sys.modules,
            "teleclaude.cli.session_auth",
            SimpleNamespace(resolve_cli_caller_role=lambda: "member"),
        )
        docs._handle_docs_index(
            ["--baseline-only", "--third-party", "--areas", "policy,procedure", "--domains", "software-development"]
        )

    assert received == [
        {
            "areas": ["policy", "procedure"],
            "project_root": tmp_path,
            "snippet_ids": None,
            "baseline_only": True,
            "include_third_party": True,
            "domains": ["software-development"],
            "effective_human_role": "member",
        }
    ]
    assert capsys.readouterr().out == "INDEX\n"


def test_handle_docs_get_splits_snippet_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    received: list[ContextCall] = []

    monkeypatch.chdir(tmp_path)

    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            sys.modules,
            "teleclaude.context_selector",
            SimpleNamespace(build_context_output=lambda **kwargs: received.append(kwargs) or "GET"),
        )
        sys_patch.setitem(
            sys.modules,
            "teleclaude.cli.session_auth",
            SimpleNamespace(resolve_cli_caller_role=lambda: "member"),
        )
        docs._handle_docs_get(["a,b", "c"])

    assert received[0]["snippet_ids"] == ["a", "b", "c"]
    assert received[0]["project_root"] == tmp_path
    assert capsys.readouterr().out == "GET\n"


def test_handle_docs_get_requires_at_least_one_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(docs, "_usage", lambda *args: f"usage:{'/'.join(args)}")

    with pytest.raises(SystemExit) as exc_info:
        docs._handle_docs_get([])

    assert exc_info.value.code == 1
    assert capsys.readouterr().out.strip()
