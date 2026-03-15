"""Characterization tests for teleclaude.project_setup.init_flow."""

from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import teleclaude.project_setup.init_flow as init_flow


def test_is_teleclaude_project_detects_repo_layout(tmp_path: Path) -> None:
    marker = tmp_path / "teleclaude" / "project_setup" / "init_flow.py"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("# marker\n", encoding="utf-8")

    assert init_flow._is_teleclaude_project(tmp_path) is True
    assert init_flow._is_teleclaude_project(tmp_path / "other") is False


def test_prompt_yes_no_returns_default_when_stdin_is_not_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(init_flow.sys, "stdin", SimpleNamespace(isatty=lambda: False))

    assert init_flow._prompt_yes_no("Proceed?", default=False) is False


def test_prompt_release_channel_updates_stable_channel_and_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        "deployment:\n  channel: alpha\n  pinned_minor: ''\n",
        encoding="utf-8",
    )
    answers = iter(["stable", "1.2"])
    monkeypatch.setattr(init_flow.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    init_flow._prompt_release_channel(tmp_path)

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert payload["deployment"] == {"channel": "stable", "pinned_minor": "1.2"}


def test_offer_enrichment_launches_refresh_for_reinitialized_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launches: list[object] = []
    monkeypatch.setattr(init_flow.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(init_flow, "_has_generated_snippets", lambda project_root: True)
    monkeypatch.setattr(init_flow, "_prompt_yes_no", lambda prompt: True)
    monkeypatch.setattr(init_flow, "_launch_enrichment", lambda project_root: launches.append(project_root))

    init_flow._offer_enrichment(tmp_path)

    assert launches == [tmp_path]
