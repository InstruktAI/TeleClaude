from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

demo = importlib.import_module("teleclaude.cli.telec.handlers.demo")


def test_handle_todo_demo_defaults_to_list_for_empty_args(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    received: list[Path] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(demo, "_demo_list", lambda project_root: received.append(project_root))

    demo._handle_todo_demo([])

    assert received == [tmp_path]


def test_handle_todo_demo_treats_slug_as_run_shorthand(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    received: list[tuple[str, Path]] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(demo, "_demo_run", lambda slug, project_root: received.append((slug, project_root)))

    demo._handle_todo_demo(["sample-slug"])

    assert received == [("sample-slug", tmp_path)]


def test_handle_todo_demo_rejects_slug_for_list(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(demo, "_usage", lambda *args: f"usage:{'/'.join(args)}")

    with pytest.raises(SystemExit) as exc_info:
        demo._handle_todo_demo(["list", "sample-slug"])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "does not take a slug" in captured.out
    assert "usage:todo/demo" in captured.out


def test_demo_create_promotes_demo_and_writes_snapshot(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_root = tmp_path
    source = project_root / "todos" / "sample-slug" / "demo.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Demo: Sample Feature\n\nSome content\n", encoding="utf-8")
    (project_root / "pyproject.toml").write_text('[project]\nversion = "2.4.6"\n', encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        demo._demo_create("sample-slug", project_root)

    assert exc_info.value.code == 0
    promoted = project_root / "demos" / "sample-slug"
    assert (promoted / "demo.md").read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert json.loads((promoted / "snapshot.json").read_text(encoding="utf-8")) == {
        "slug": "sample-slug",
        "title": "Sample Feature",
        "version": "2.4.6",
    }
    captured = capsys.readouterr()
    assert "Demo promoted: todos/sample-slug/demo.md -> demos/sample-slug/" in captured.out


def test_demo_list_reports_available_missing_and_broken_snapshots(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    demos_dir = tmp_path / "demos"
    good_dir = demos_dir / "good-demo"
    missing_dir = demos_dir / "missing-demo"
    broken_dir = demos_dir / "broken-demo"

    good_dir.mkdir(parents=True)
    missing_dir.mkdir(parents=True)
    broken_dir.mkdir(parents=True)

    (good_dir / "snapshot.json").write_text(
        json.dumps(
            {
                "title": "Good Demo",
                "version": "1.2.3",
                "delivered_date": "2025-01-01",
            }
        ),
        encoding="utf-8",
    )
    (broken_dir / "snapshot.json").write_text("{not-json", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        demo._demo_list(tmp_path)

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "Available demos (1):" in output
    assert "good-demo" in output
    assert "Missing snapshot.json (1):" in output
    assert "missing-demo" in output
    assert "Broken snapshot.json (1):" in output
    assert "broken-demo" in output


def test_demo_validate_warns_for_no_demo_marker(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo_md = tmp_path / "todos" / "sample-slug" / "demo.md"
    demo_md.parent.mkdir(parents=True)
    demo_md.write_text(
        "# Demo: Sample\n<!-- no-demo: internal refactor only -->\n\nNo executable steps.\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        demo._demo_validate("sample-slug", tmp_path)

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "WARNING: no-demo marker found: internal refactor only" in output
    assert "Reviewer must verify justification" in output


def test_demo_run_executes_non_skipped_blocks_with_project_venv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    demo_md = tmp_path / "todos" / "sample-slug" / "demo.md"
    demo_md.parent.mkdir(parents=True)
    demo_md.write_text(
        "\n".join(
            [
                "# Demo: Sample",
                "",
                "<!-- skip-validation: depends on external service -->",
                "```bash",
                "echo skipped",
                "```",
                "",
                "```bash",
                "python -m sample_command",
                "```",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / ".venv" / "bin").mkdir(parents=True)

    completed = SimpleNamespace(returncode=0)
    run = MagicMock(return_value=completed)
    monkeypatch.setattr(demo.subprocess, "run", run)

    with pytest.raises(SystemExit) as exc_info:
        demo._demo_run("sample-slug", tmp_path)

    assert exc_info.value.code == 0
    run.assert_called_once()
    assert run.call_args.args[0] == "python -m sample_command"
    assert run.call_args.kwargs["shell"] is True
    assert run.call_args.kwargs["cwd"] == tmp_path
    assert run.call_args.kwargs["env"]["PATH"].startswith(str(tmp_path / ".venv" / "bin"))
    assert run.call_args.kwargs["env"]["VIRTUAL_ENV"] == str(tmp_path / ".venv")
    output = capsys.readouterr().out
    assert "SKIP  block at line 4: depends on external service" in output
    assert "RUN   block at line 8: python -m sample_command" in output
    assert "Demo passed: 1/1 blocks" in output
