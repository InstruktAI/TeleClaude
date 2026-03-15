from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

roadmap = importlib.import_module("teleclaude.cli.telec.handlers.roadmap")


def test_parse_roadmap_show_args_sets_requested_flags() -> None:
    parsed = roadmap._parse_roadmap_show_args(["--include-icebox", "--delivered-only", "--json"])

    assert parsed == {
        "include_icebox": True,
        "icebox_only": False,
        "include_delivered": False,
        "delivered_only": True,
        "json_output": True,
    }


def test_handle_roadmap_show_prints_json_when_requested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    todos = [SimpleNamespace(to_dict=lambda: {"slug": "sample", "status": "ready"})]

    monkeypatch.chdir(tmp_path)
    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            sys.modules,
            "teleclaude.core.roadmap",
            SimpleNamespace(assemble_roadmap=lambda *args, **kwargs: todos),
        )
        roadmap._handle_roadmap_show(["--json"])

    assert json.loads(capsys.readouterr().out) == [{"slug": "sample", "status": "ready"}]


def test_handle_roadmap_add_forwards_parsed_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, str, str | None, list[str] | None, str | None, str | None]] = []

    monkeypatch.chdir(tmp_path)
    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            sys.modules,
            "teleclaude.core.next_machine.core",
            SimpleNamespace(
                add_to_roadmap=lambda cwd, slug, *, group, after, description, before: (
                    calls.append((cwd, slug, group, after, description, before)) or True
                )
            ),
        )
        roadmap._handle_roadmap_add(
            ["sample", "--group", "core", "--after", "dep-a,dep-b", "--description", "Demo", "--before", "other"]
        )

    assert calls == [(str(tmp_path), "sample", "core", ["dep-a", "dep-b"], "Demo", "other")]
    assert "Added sample to roadmap." in capsys.readouterr().out


def test_handle_roadmap_deliver_runs_cleanup_and_git_steps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess_calls: list[list[str]] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        roadmap.subprocess,
        "run",
        lambda args, **kwargs: subprocess_calls.append(args) or SimpleNamespace(returncode=1),
    )

    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            sys.modules,
            "teleclaude.core.next_machine.core",
            SimpleNamespace(
                deliver_to_delivered=lambda cwd, slug, commit=None: True,
                cleanup_delivered_slug=lambda cwd, slug: None,
            ),
        )
        roadmap._handle_roadmap_deliver(["sample", "--commit", "abc123"])

    assert subprocess_calls[0][:2] == ["git", "add"]
    assert subprocess_calls[1] == ["git", "diff", "--cached", "--quiet"]
    assert subprocess_calls[2][:2] == ["git", "commit"]
    assert "Delivered sample" in capsys.readouterr().out
