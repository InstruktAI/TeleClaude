"""Regression guardrails for adapter/shared boundary purity."""

import ast
from pathlib import Path


def _get_class_method_source(path: Path, class_name: str, method_name: str) -> str:
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    segment = ast.get_source_segment(source, child)
                    if segment:
                        return segment
    raise AssertionError(f"Method {class_name}.{method_name} not found in {path}")


def test_adapter_client_run_ui_lane_stays_adapter_agnostic() -> None:
    """Shared UI lane orchestration must not include Telegram-specific recovery branches."""
    method_source = _get_class_method_source(
        Path("teleclaude/core/adapter_client.py"),
        "AdapterClient",
        "_run_ui_lane",
    )

    assert 'adapter_type == "telegram"' not in method_source
    assert "message thread not found" not in method_source
    assert "topic_deleted" not in method_source


def test_telegram_adapter_owns_missing_thread_recovery() -> None:
    """Platform-specific missing-thread handling belongs in Telegram adapter code."""
    source = Path("teleclaude/adapters/telegram_adapter.py").read_text(encoding="utf-8")

    assert "message thread not found" in source
    assert "topic_deleted" in source
    assert "_reset_stale_topic_state" in source
