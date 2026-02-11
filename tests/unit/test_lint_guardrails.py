"""Unit tests for loose-dict guardrail marker handling."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

LOOSE_DICT_LITERAL = "dict[str, " + "object]"


def _load_guardrails_module():
    path = Path(__file__).resolve().parents[2] / "tools" / "lint" / "guardrails.py"
    spec = importlib.util.spec_from_file_location("lint_guardrails", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_line_has_exception_marker_on_same_line() -> None:
    module = _load_guardrails_module()
    lines = [f"value: {LOOSE_DICT_LITERAL}  # guard: loose-dict - dynamic payload"]
    markers = ("# guard: loose-dict", "# guard:loose-dict", "# guard: loose-dict-func")
    assert module._line_has_exception_marker(lines, 1, markers) is True


def test_line_has_exception_marker_on_previous_line() -> None:
    module = _load_guardrails_module()
    lines = [
        "# guard: loose-dict - boundary JSON payload",
        f"value: {LOOSE_DICT_LITERAL}",
    ]
    markers = ("# guard: loose-dict", "# guard:loose-dict", "# guard: loose-dict-func")
    assert module._line_has_exception_marker(lines, 2, markers) is True


def test_line_without_marker_is_not_exempt() -> None:
    module = _load_guardrails_module()
    lines = [
        "# unrelated comment",
        f"value: {LOOSE_DICT_LITERAL}",
    ]
    markers = ("# guard: loose-dict", "# guard:loose-dict", "# guard: loose-dict-func")
    assert module._line_has_exception_marker(lines, 2, markers) is False


def test_legacy_noqa_loose_dict_marker_fails(tmp_path: Path) -> None:
    module = _load_guardrails_module()
    file_path = tmp_path / "teleclaude" / "example.py"
    file_path.parent.mkdir(parents=True)
    loose_dict = "dict[str, " + "object]"
    legacy_marker = "# noqa: " + "loose-dict - legacy marker"
    file_path.write_text(
        f"data: {loose_dict}  {legacy_marker}\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="legacy loose-dict marker detected"):
        module._warn_for_loose_dicts(tmp_path)


def test_debug_probe_prints_fail_guardrails(tmp_path: Path) -> None:
    module = _load_guardrails_module()
    file_path = tmp_path / "teleclaude" / "example.py"
    file_path.parent.mkdir(parents=True)
    debug_prefix = "DEBUG" + ":"
    file_path.write_text(
        f'print("{debug_prefix} temporary probe")\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="leftover debug probe prints detected"):
        module._warn_for_debug_probes(tmp_path)


def test_stash_commands_in_agent_artifacts_fail_guardrails(tmp_path: Path) -> None:
    module = _load_guardrails_module()
    file_path = tmp_path / "agents" / "commands" / "next-build.md"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(
        "Run `git stash` before switching tasks.\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="forbidden git stash command usage"):
        module._fail_on_stash_commands_in_agent_artifacts(tmp_path)


def test_stash_commands_allowlisted_with_marker(tmp_path: Path) -> None:
    module = _load_guardrails_module()
    file_path = tmp_path / "agents" / "commands" / "example.md"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(
        "guard: allow-git-stash\nThis line documents `git stash` for explanation only.\n",
        encoding="utf-8",
    )

    module._fail_on_stash_commands_in_agent_artifacts(tmp_path)
