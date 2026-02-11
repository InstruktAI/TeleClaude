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


def test_adapter_client_run_ui_lane_no_raw_platform_strings() -> None:
    """Shared UI lane must not embed raw platform-specific error strings."""
    method_source = _get_class_method_source(
        Path("teleclaude/core/adapter_client.py"),
        "AdapterClient",
        "_run_ui_lane",
    )

    # Raw detection strings belong in helper methods, not inline in the lane
    assert "message thread not found" not in method_source
    assert "topic_deleted" not in method_source


def test_telegram_adapter_owns_missing_thread_recovery() -> None:
    """Missing-thread detection lives in the Telegram message ops mixin."""
    message_ops_source = Path("teleclaude/adapters/telegram/message_ops.py").read_text(encoding="utf-8")

    assert "message thread not found" in message_ops_source
