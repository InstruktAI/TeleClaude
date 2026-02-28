"""Integration tests for telec CLI command chains (non-TUI)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typing_extensions import TypedDict

from teleclaude.cli import telec


class DocsInvocation(TypedDict, total=False):
    project_root: Path
    baseline_only: bool
    include_third_party: bool
    areas: list[str]
    domains: list[str] | None
    snippet_ids: list[str] | None


class SyncInvocation(TypedDict, total=False):
    project_root: Path
    validate_only: bool
    warn_only: bool


@pytest.mark.integration
def test_docs_phase1_parses_flags_and_calls_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """telec docs index should parse flags and call context selector."""
    captured: DocsInvocation = {}

    def fake_build_context_output(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "INDEX_OUTPUT"

    from teleclaude import context_selector

    monkeypatch.setattr(context_selector, "build_context_output", fake_build_context_output)
    monkeypatch.chdir(tmp_path)

    telec._handle_docs(
        [
            "index",
            "--baseline-only",
            "--third-party",
            "--areas",
            "policy,procedure",
            "--domains",
            "software-development,general",
        ]
    )

    output = capsys.readouterr().out
    assert "INDEX_OUTPUT" in output
    assert captured["project_root"] == tmp_path.resolve()
    assert captured["baseline_only"] is True
    assert captured["include_third_party"] is True
    assert captured["areas"] == ["policy", "procedure"]
    assert captured["domains"] == ["software-development", "general"]
    assert captured["snippet_ids"] is None


@pytest.mark.integration
def test_docs_phase2_ignores_filters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """telec docs get should fetch snippet IDs and ignore index-only filters."""
    captured: DocsInvocation = {}

    def fake_build_context_output(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "SNIPPET_OUTPUT"

    from teleclaude import context_selector

    monkeypatch.setattr(context_selector, "build_context_output", fake_build_context_output)
    monkeypatch.chdir(tmp_path)

    telec._handle_docs(
        [
            "get",
            "general/policy/one,general/policy/two",
            "software-development/policy/three",
        ]
    )

    output = capsys.readouterr().out
    assert "SNIPPET_OUTPUT" in output
    assert captured["project_root"] == tmp_path.resolve()
    assert captured["areas"] == []
    assert captured["baseline_only"] is False
    assert captured["include_third_party"] is False
    assert captured["domains"] is None
    assert captured["snippet_ids"] == [
        "general/policy/one",
        "general/policy/two",
        "software-development/policy/three",
    ]


@pytest.mark.integration
def test_sync_validate_only_calls_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """telec sync should pass validate_only to sync()."""
    captured: SyncInvocation = {}

    def fake_sync(project_root: Path, *, validate_only: bool, warn_only: bool) -> bool:
        captured.update(
            {
                "project_root": project_root,
                "validate_only": validate_only,
                "warn_only": warn_only,
            }
        )
        return True

    from teleclaude import sync as sync_module

    monkeypatch.setattr(sync_module, "sync", fake_sync)
    monkeypatch.chdir(tmp_path)

    telec._handle_sync(["--validate-only"])

    assert captured["project_root"] == tmp_path.resolve()
    assert captured["validate_only"] is True
    assert captured["warn_only"] is False


@pytest.mark.integration
def test_sync_failure_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    """telec sync should exit non-zero when sync() fails."""

    def fake_sync(project_root: Path, *, validate_only: bool, warn_only: bool) -> bool:
        _ = (project_root, validate_only, warn_only)
        return False

    from teleclaude import sync as sync_module

    monkeypatch.setattr(sync_module, "sync", fake_sync)

    with pytest.raises(SystemExit) as excinfo:
        telec._handle_sync([])

    assert excinfo.value.code == 1


@pytest.mark.integration
def test_init_calls_init_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """telec init should call init_project with cwd."""
    called: dict[str, Path] = {}

    def fake_init(path: Path) -> None:
        called["path"] = path

    monkeypatch.setattr(telec, "init_project", fake_init)
    monkeypatch.setattr(telec.Path, "cwd", lambda: tmp_path)

    telec._handle_cli_command(["init"])

    assert called["path"] == tmp_path


@pytest.mark.integration
def test_completion_docs_flags(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Shell completion should include docs flags when requested."""
    monkeypatch.setenv("TELEC_COMPLETE", "1")
    monkeypatch.setenv("COMP_LINE", "telec docs index --a")

    telec.main()

    output = capsys.readouterr().out
    assert "--areas" in output


@pytest.mark.integration
def test_sessions_run_help_exposes_command_interface(capsys: pytest.CaptureFixture[str]) -> None:
    """sessions run --help should expose usage, required flags, and examples."""
    telec._handle_cli_command(["sessions", "run", "--help"])
    output = capsys.readouterr().out
    assert "Usage:" in output
    assert "telec sessions run" in output
    assert "--command" in output
    assert "--project" in output
    assert "Examples:" in output
    assert "/next-build" in output


@pytest.mark.integration
def test_docs_help_exposes_ids_and_filters(capsys: pytest.CaptureFixture[str]) -> None:
    """docs --help should expose explicit index/get subcommands and examples."""
    telec._handle_cli_command(["docs", "--help"])
    output = capsys.readouterr().out
    assert "Usage:" in output
    assert "telec docs index" in output
    assert "telec docs get <id> [id...]" in output
    assert "--areas" in output
    assert "--domains" in output
    assert "Example phase 1:" in output
    assert "Example phase 2:" in output
    assert "telec docs get software-development/policy/testing" in output


@pytest.mark.integration
def test_config_help_exposes_second_level_actions(capsys: pytest.CaptureFixture[str]) -> None:
    telec._handle_cli_command(["config", "--help"])
    output = capsys.readouterr().out
    assert "telec config people list" in output
    assert "telec config people add" in output
    assert "telec config people edit" in output
    assert "telec config people remove" in output
    assert "telec config env list" in output
    assert "telec config env set" in output
