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
    """telec docs phase 1 should parse flags and call context selector."""
    captured: DocsInvocation = {}

    def fake_build_context_output(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "INDEX_OUTPUT"

    from teleclaude import context_selector

    monkeypatch.setattr(context_selector, "build_context_output", fake_build_context_output)

    telec._handle_docs(
        [
            "--project-root",
            str(tmp_path),
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
    """telec docs phase 2 ignores filter flags when snippet IDs are supplied."""
    captured: DocsInvocation = {}

    def fake_build_context_output(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "SNIPPET_OUTPUT"

    from teleclaude import context_selector

    monkeypatch.setattr(context_selector, "build_context_output", fake_build_context_output)

    telec._handle_docs(
        [
            "--project-root",
            str(tmp_path),
            "--areas",
            "policy",
            "--baseline-only",
            "--third-party",
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

    telec._handle_sync(["--project-root", str(tmp_path), "--validate-only"])

    assert captured["project_root"] == tmp_path.resolve()
    assert captured["validate_only"] is True
    assert captured["warn_only"] is False


@pytest.mark.integration
def test_sync_failure_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """telec sync should exit non-zero when sync() fails."""

    def fake_sync(_project_root: Path, *, validate_only: bool, warn_only: bool) -> bool:
        _ = (validate_only, warn_only)
        return False

    from teleclaude import sync as sync_module

    monkeypatch.setattr(sync_module, "sync", fake_sync)

    with pytest.raises(SystemExit) as excinfo:
        telec._handle_sync(["--project-root", str(tmp_path)])

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
    monkeypatch.setenv("COMP_LINE", "telec docs --a")

    telec.main()

    output = capsys.readouterr().out
    assert "--areas" in output
