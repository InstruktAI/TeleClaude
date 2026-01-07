"""Unit tests for telec CLI helpers."""

from __future__ import annotations

from teleclaude.cli import telec as telec_module


def test_build_terminal_metadata_includes_terminal_payload() -> None:
    metadata = telec_module._build_terminal_metadata(
        tty_path="/dev/pts/7",
        parent_pid=4242,
        cols=120,
        rows=40,
        cwd="/tmp/project",
        auto_command="agent claude slow",
    )

    assert metadata.adapter_type == "terminal"
    assert metadata.project_dir == "/tmp/project"
    assert metadata.auto_command == "agent claude slow"
    assert metadata.channel_metadata == {
        "terminal": {
            "tty_path": "/dev/pts/7",
            "parent_pid": 4242,
            "terminal_size": "120x40",
        }
    }
