from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict

import pytest

from teleclaude.config.schema import AppConfig, GlobalConfig

docs = importlib.import_module("teleclaude.cli.telec.handlers.docs")


class ContextCall(TypedDict):
    areas: list[str]
    project_root: Path
    snippet_ids: list[str] | None
    baseline_only: bool
    include_third_party: bool
    domains: list[str] | None
    effective_human_role: str | None
    config: AppConfig


def test_handle_docs_help_prints_usage(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        docs,
        "_usage",
        lambda *args: f"usage:{'/'.join(args)}",  # pyright: ignore[reportUnknownLambdaType]
    )

    docs._handle_docs(["--help"])

    assert capsys.readouterr().out == "usage:docs\n"


def test_handle_docs_index_builds_context_with_filters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    received: list[ContextCall] = []
    mock_config = AppConfig(global_=GlobalConfig())

    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        docs,
        "build_context_output",
        lambda **kwargs: received.append(kwargs) or "INDEX",  # pyright: ignore[reportUnknownLambdaType]
    )
    monkeypatch.setattr(
        docs,
        "load_app_config",
        lambda _: mock_config,  # pyright: ignore[reportUnknownLambdaType]
    )
    monkeypatch.setattr(docs, "read_current_session_email", lambda: "member@example.com")
    mock_resolver = SimpleNamespace(resolve_by_email=lambda email: SimpleNamespace(person_role="member", email=email))
    monkeypatch.setattr(docs, "get_identity_resolver", lambda: mock_resolver)

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
            "config": mock_config,
        }
    ]
    assert capsys.readouterr().out == "INDEX\n"


def test_handle_docs_get_splits_snippet_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    received: list[ContextCall] = []

    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        docs,
        "build_context_output",
        lambda **kwargs: received.append(kwargs) or "GET",  # pyright: ignore[reportUnknownLambdaType]
    )
    monkeypatch.setattr(
        docs,
        "load_app_config",
        lambda _: AppConfig(global_=GlobalConfig()),  # pyright: ignore[reportUnknownLambdaType]
    )
    monkeypatch.setattr(docs, "read_current_session_email", lambda: "member@example.com")
    mock_resolver = SimpleNamespace(resolve_by_email=lambda email: SimpleNamespace(person_role="member", email=email))
    monkeypatch.setattr(docs, "get_identity_resolver", lambda: mock_resolver)

    docs._handle_docs_get(["a,b", "c"])

    assert received[0]["snippet_ids"] == ["a", "b", "c"]
    assert received[0]["project_root"] == tmp_path
    assert capsys.readouterr().out == "GET\n"


def test_handle_docs_index_passes_none_role_when_unauthed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    received: list[ContextCall] = []
    mock_config = AppConfig(global_=GlobalConfig())

    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        docs,
        "build_context_output",
        lambda **kwargs: received.append(kwargs) or "INDEX",  # pyright: ignore[reportUnknownLambdaType]
    )
    monkeypatch.setattr(
        docs,
        "load_app_config",
        lambda _: mock_config,  # pyright: ignore[reportUnknownLambdaType]
    )
    monkeypatch.setattr(docs, "read_current_session_email", lambda: None)

    docs._handle_docs_index([])

    assert received[0]["effective_human_role"] is None
    assert capsys.readouterr().out == "INDEX\n"


def test_handle_docs_get_requires_at_least_one_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        docs,
        "_usage",
        lambda *args: f"usage:{'/'.join(args)}",  # pyright: ignore[reportUnknownLambdaType]
    )

    with pytest.raises(SystemExit) as exc_info:
        docs._handle_docs_get([])

    assert exc_info.value.code == 1
    assert capsys.readouterr().out.strip()
