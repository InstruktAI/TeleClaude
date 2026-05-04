"""Tests for session-scoping native extractors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import teleclaude.session_scoping._extractors as extractor_dispatch
import teleclaude.session_scoping._extractors.claude as claude_extractor
import teleclaude.session_scoping._extractors.codex as codex_extractor
import teleclaude.session_scoping._extractors.gemini as gemini_extractor
from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline


def test_codex_extractor_ignores_shell_tools_and_keeps_structured_mutators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeline = TurnTimeline(
        has_data=True,
        tool_calls=[
            ToolCallRecord(
                tool_name="functions.exec_command",
                input_data={"cmd": "touch src/ignored.py"},
                had_error=False,
            ),
            ToolCallRecord(
                tool_name="apply_patch",
                input_data={"input": "*** Begin Patch\n*** Add File: src/kept.py\n*** End Patch\n"},
                had_error=False,
            ),
        ],
    )
    monkeypatch.setattr(codex_extractor, "extract_effective_tool_calls", lambda *args, **kwargs: timeline)

    paths, strategy = codex_extractor.collect_codex_paths(
        transcript_path="/tmp/session.jsonl",
        native_session_id="native-1",
        workspace_root="/repo",
        scope_mode="turn_delta",
    )

    assert paths == {"src/kept.py"}
    assert strategy == "codex_structured"


def test_codex_extractor_normalizes_patch_apply_event_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    timeline = TurnTimeline(
        has_data=True,
        tool_calls=[
            ToolCallRecord(
                tool_name="apply_patch",
                input_data={"paths": ["/repo/src/kept.py", "/repo/tests/test_kept.py"]},
                had_error=False,
            ),
        ],
    )
    monkeypatch.setattr(codex_extractor, "extract_effective_tool_calls", lambda *args, **kwargs: timeline)

    paths, strategy = codex_extractor.collect_codex_paths(
        transcript_path="/tmp/session.jsonl",
        native_session_id="native-1",
        workspace_root="/repo",
        scope_mode="turn_delta",
    )

    assert paths == {"src/kept.py", "tests/test_kept.py"}
    assert strategy == "codex_structured"


def test_claude_extractor_uses_file_history_delta_for_turn_scope(tmp_path: Path) -> None:
    transcript = tmp_path / "claude.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"message": {"role": "user", "content": "turn one"}}),
                json.dumps(
                    {
                        "type": "file-history-snapshot",
                        "snapshot": {"trackedFileBackups": {"src/already_seen.py": {"version": 1}}},
                    }
                ),
                json.dumps({"message": {"role": "user", "content": "turn two"}}),
                json.dumps(
                    {
                        "type": "file-history-snapshot",
                        "snapshot": {
                            "trackedFileBackups": {
                                "src/already_seen.py": {"version": 1},
                                "src/new_in_turn.py": {"version": 1},
                            }
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    paths, strategy = claude_extractor.collect_claude_paths(
        transcript_path=str(transcript),
        workspace_root=str(tmp_path),
        scope_mode="turn_delta",
    )

    assert paths == {"src/new_in_turn.py"}
    assert strategy == "claude_file_history"


def test_claude_extractor_falls_back_to_structured_write_edit_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    timeline = TurnTimeline(
        has_data=True,
        tool_calls=[
            ToolCallRecord(tool_name="Write", input_data={"file_path": "src/fallback.py"}, had_error=False),
            ToolCallRecord(tool_name="Edit", input_data={"file_path": "src/also_kept.py"}, had_error=False),
        ],
    )
    monkeypatch.setattr(claude_extractor, "_get_entries_for_agent", lambda *args, **kwargs: [])
    monkeypatch.setattr(claude_extractor, "extract_effective_tool_calls", lambda *args, **kwargs: timeline)

    paths, strategy = claude_extractor.collect_claude_paths(
        transcript_path="/tmp/session.jsonl",
        workspace_root="/repo",
        scope_mode="session_dirty",
    )

    assert paths == {"src/also_kept.py", "src/fallback.py"}
    assert strategy == "claude_structured_fallback"


def test_claude_extractor_normalizes_absolute_snapshot_paths(tmp_path: Path) -> None:
    transcript = tmp_path / "claude.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "file-history-snapshot",
                "snapshot": {
                    "trackedFileBackups": {
                        str((tmp_path / "src" / "absolute.py").resolve()): {"version": 1},
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    paths, strategy = claude_extractor.collect_claude_paths(
        transcript_path=str(transcript),
        workspace_root=str(tmp_path),
        scope_mode="session_dirty",
    )

    assert paths == {"src/absolute.py"}
    assert strategy == "claude_file_history"


def test_gemini_extractor_uses_successful_explicit_file_tools_only(tmp_path: Path) -> None:
    transcript = tmp_path / "gemini.json"
    transcript.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "type": "user",
                        "content": "first turn",
                    },
                    {
                        "type": "gemini",
                        "toolCalls": [
                            {
                                "name": "WriteFile",
                                "status": "success",
                                "args": {"file_path": "src/older.py"},
                            }
                        ],
                    },
                    {
                        "type": "user",
                        "content": "second turn",
                    },
                    {
                        "type": "gemini",
                        "toolCalls": [
                            {
                                "name": "Shell",
                                "status": "success",
                                "args": {"command": "touch src/ignored.py"},
                            },
                            {
                                "name": "Edit",
                                "status": "success",
                                "args": {"file_path": "src/kept.py"},
                            },
                            {
                                "name": "WriteFile",
                                "status": "failed",
                                "args": {"file_path": "src/failed.py"},
                            },
                            {
                                "name": "WriteFile",
                                "status": "success",
                                "args": {"file_path": "src/kept_too.py"},
                            },
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    turn_paths, turn_strategy = gemini_extractor.collect_gemini_paths(
        transcript_path=str(transcript),
        workspace_root=str(tmp_path),
        scope_mode="turn_delta",
    )
    session_paths, session_strategy = gemini_extractor.collect_gemini_paths(
        transcript_path=str(transcript),
        workspace_root=str(tmp_path),
        scope_mode="session_dirty",
    )

    assert turn_paths == {"src/kept.py", "src/kept_too.py"}
    assert turn_strategy == "gemini_structured"
    assert session_paths == {"src/kept.py", "src/kept_too.py", "src/older.py"}
    assert session_strategy == "gemini_structured"


def test_gemini_extractor_normalizes_absolute_workspace_paths(tmp_path: Path) -> None:
    transcript = tmp_path / "gemini.json"
    transcript.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "type": "gemini",
                        "toolCalls": [
                            {
                                "name": "WriteFile",
                                "status": "success",
                                "args": {"file_path": str((tmp_path / "src" / "absolute.py").resolve())},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    paths, strategy = gemini_extractor.collect_gemini_paths(
        transcript_path=str(transcript),
        workspace_root=str(tmp_path),
        scope_mode="session_dirty",
    )

    assert paths == {"src/absolute.py"}
    assert strategy == "gemini_structured"


def test_shared_scoping_package_has_no_dependency_on_shell_heuristic_helpers() -> None:
    package_root = Path(__file__).resolve().parents[3] / "teleclaude" / "session_scoping"
    package_source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(package_root.rglob("*.py")))

    assert "_command_likely_mutates_files" not in package_source
    assert "_extract_shell_touched_paths" not in package_source


def test_dispatch_selects_supported_agents() -> None:
    assert extractor_dispatch.resolve_extractor("codex") is codex_extractor.collect_codex_paths
    assert extractor_dispatch.resolve_extractor("claude") is claude_extractor.collect_claude_paths
    assert extractor_dispatch.resolve_extractor("gemini") is gemini_extractor.collect_gemini_paths
