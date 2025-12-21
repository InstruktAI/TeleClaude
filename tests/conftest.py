"""Pytest configuration for TeleClaude tests."""

import logging

import pytest

try:
    import instrukt_ai_logging

    def _noop_configure_logging(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return None

    instrukt_ai_logging.configure_logging = _noop_configure_logging  # type: ignore[assignment]
    logging.getLogger("teleclaude").handlers.clear()
    logging.getLogger().handlers.clear()
except Exception:
    pass


def pytest_collection_modifyitems(config, items):
    """Set per-marker timeouts: unit=1s, integration=5s."""
    for item in items:
        if "unit" in item.keywords:
            item.add_marker(pytest.mark.timeout(1))
        elif "integration" in item.keywords:
            item.add_marker(pytest.mark.timeout(5))
