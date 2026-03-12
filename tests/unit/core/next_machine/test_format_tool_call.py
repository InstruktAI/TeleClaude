"""Tests for Task 12: additional_context parameter in format_tool_call."""

from __future__ import annotations

from teleclaude.core.next_machine.core import format_tool_call


def _base_kwargs() -> dict:
    return {
        "command": "next-build",
        "args": "my-slug",
        "project": "/repo",
        "guidance": "guidance text",
        "subfolder": "",
    }


def test_format_tool_call_with_additional_context_includes_block() -> None:
    result = format_tool_call(**_base_kwargs(), additional_context="diff --git a/foo.py")
    assert "ADDITIONAL CONTEXT FOR WORKER:" in result
    assert "diff --git a/foo.py" in result


def test_format_tool_call_with_additional_context_includes_flag() -> None:
    result = format_tool_call(**_base_kwargs(), additional_context="some context")
    assert '--additional-context "some context"' in result


def test_format_tool_call_without_additional_context_omits_block() -> None:
    result = format_tool_call(**_base_kwargs())
    assert "ADDITIONAL CONTEXT FOR WORKER:" not in result
    assert "--additional-context" not in result


def test_format_tool_call_empty_additional_context_omits_block() -> None:
    result = format_tool_call(**_base_kwargs(), additional_context="")
    assert "ADDITIONAL CONTEXT FOR WORKER:" not in result
    assert "--additional-context" not in result
