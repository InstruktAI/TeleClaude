"""Pytest configuration for TeleClaude tests."""

import pytest


def pytest_collection_modifyitems(config, items):
    """Set per-marker timeouts: unit=1s, integration=5s."""
    for item in items:
        if "unit" in item.keywords:
            item.add_marker(pytest.mark.timeout(1))
        elif "integration" in item.keywords:
            item.add_marker(pytest.mark.timeout(5))
