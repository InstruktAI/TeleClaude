"""Characterization tests for teleclaude/cli/watch.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.cli.watch import SmartWatcher


def _noop_sync(self: SmartWatcher) -> None:
    pass


# ---------------------------------------------------------------------------
# SmartWatcher._is_sync_relevant (classmethod, pure logic)
# ---------------------------------------------------------------------------


def test_is_sync_relevant_returns_true_for_docs_path() -> None:
    assert SmartWatcher._is_sync_relevant(Path("docs/foo/bar.md")) is True


def test_is_sync_relevant_returns_true_for_agents_path() -> None:
    assert SmartWatcher._is_sync_relevant(Path("agents/my-agent.md")) is True


def test_is_sync_relevant_returns_true_for_dot_agents_path() -> None:
    assert SmartWatcher._is_sync_relevant(Path(".agents/config.yaml")) is True


def test_is_sync_relevant_returns_true_for_agents_master_filename() -> None:
    assert SmartWatcher._is_sync_relevant(Path("AGENTS.master.md")) is True


def test_is_sync_relevant_returns_true_for_agents_global_filename() -> None:
    assert SmartWatcher._is_sync_relevant(Path("AGENTS.global.md")) is True


def test_is_sync_relevant_returns_false_for_unrelated_path() -> None:
    assert SmartWatcher._is_sync_relevant(Path("src/main.py")) is False


def test_is_sync_relevant_returns_false_for_tilde_backup() -> None:
    assert SmartWatcher._is_sync_relevant(Path("docs/notes~")) is False


def test_is_sync_relevant_returns_false_for_swp_file() -> None:
    assert SmartWatcher._is_sync_relevant(Path("docs/.notes.swp")) is False


def test_is_sync_relevant_returns_false_for_tmp_file() -> None:
    assert SmartWatcher._is_sync_relevant(Path("docs/notes.tmp.yaml")) is False


def test_is_sync_relevant_returns_false_for_generated_index() -> None:
    assert SmartWatcher._is_sync_relevant(Path("docs/sub/index.yaml")) is False


def test_is_sync_relevant_returns_false_for_empty_path() -> None:
    assert SmartWatcher._is_sync_relevant(Path("")) is False


# ---------------------------------------------------------------------------
# SmartWatcher.__init__ — does initial sync and stores project_root
# ---------------------------------------------------------------------------


def test_smart_watcher_init_stores_project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SmartWatcher, "_sync", _noop_sync)
    watcher = SmartWatcher(tmp_path)
    assert watcher.project_root == tmp_path.resolve()


def test_smart_watcher_init_calls_initial_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _record_sync(self: SmartWatcher) -> None:
        calls.append("sync")

    monkeypatch.setattr(SmartWatcher, "_sync", _record_sync)
    SmartWatcher(tmp_path)
    assert calls == ["sync"]


def test_smart_watcher_default_debounce(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SmartWatcher, "_sync", _noop_sync)
    watcher = SmartWatcher(tmp_path)
    assert watcher.debounce_seconds == 2.0


def test_smart_watcher_custom_debounce(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SmartWatcher, "_sync", _noop_sync)
    watcher = SmartWatcher(tmp_path, debounce_seconds=5.0)
    assert watcher.debounce_seconds == 5.0


# ---------------------------------------------------------------------------
# SmartWatcher._trigger_sync — respects debounce
# ---------------------------------------------------------------------------


def test_trigger_sync_skips_when_debounce_active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _record_sync(self: SmartWatcher) -> None:
        calls.append("sync")

    monkeypatch.setattr(SmartWatcher, "_sync", _noop_sync)
    watcher = SmartWatcher(tmp_path, debounce_seconds=60.0)
    monkeypatch.setattr(SmartWatcher, "_sync", _record_sync)
    watcher.last_run_time = 1e12  # far future — debounce active
    watcher._trigger_sync()
    assert calls == []


def test_trigger_sync_runs_when_debounce_expired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _record_sync(self: SmartWatcher) -> None:
        calls.append("sync")

    monkeypatch.setattr(SmartWatcher, "_sync", _noop_sync)
    watcher = SmartWatcher(tmp_path, debounce_seconds=0.0)
    monkeypatch.setattr(SmartWatcher, "_sync", _record_sync)
    watcher.last_run_time = 0.0  # expired
    watcher._trigger_sync()
    assert calls == ["sync"]
