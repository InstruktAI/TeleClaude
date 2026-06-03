"""Integration test fixtures and hooks.

Marker-scoped subprocess reaper per
``software-development/policy/test-resource-discipline`` rule 16.
"""

from __future__ import annotations

import pytest

from teleclaude.quality.subprocess_reaper import reap_new_descendants, snapshot_descendants

pytestmark = pytest.mark.integration


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    """Reap attached subprocess descendants after every integration test.

    Integration tests can spawn real subprocesses. The per-test pytest-timeout
    flags any hang; this hookwrapper exists so a worker holding a leaked child's
    stdout pipe can still exit and print that flag instead of deadlocking.
    Scoped to ``tests/integration/`` by living in this conftest — unit tests pay
    zero psutil cost.
    """
    before = snapshot_descendants()
    yield
    reap_new_descendants(before)
