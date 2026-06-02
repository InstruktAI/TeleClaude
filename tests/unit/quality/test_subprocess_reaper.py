"""Verify the subprocess-descendant reaper kills new descendants without touching pre-existing ones."""

from __future__ import annotations

import subprocess
import time

import pytest

from teleclaude.quality.subprocess_reaper import reap_new_descendants, snapshot_descendants

pytestmark = pytest.mark.unit


def test_reap_new_descendants_kills_leaked_subprocess_and_leaves_pre_existing_alive() -> None:
    pre_existing = subprocess.Popen(["sleep", "30"])
    try:
        before = snapshot_descendants()
        assert pre_existing.pid in before

        leaked = subprocess.Popen(["sleep", "30"])
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if leaked.pid in snapshot_descendants():
                break
            time.sleep(0.02)
        assert leaked.pid in snapshot_descendants()

        killed = reap_new_descendants(before, grace_seconds=0.2)

        assert leaked.pid in killed
        try:
            leaked.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pytest.fail("leaked subprocess was not killed by reaper")

        assert pre_existing.poll() is None
    finally:
        pre_existing.kill()
        try:
            pre_existing.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass
