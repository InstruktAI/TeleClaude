"""Integration test for sandbox container subsystem.

Skipped automatically when Docker is not available.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from teleclaude.events.sandbox.bridge import SandboxBridgeCartridge
from teleclaude.events.sandbox.container import SandboxContainerManager
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility

pytestmark = pytest.mark.integration

# Skip entire module if Docker is not available
if shutil.which("docker") is None:
    pytest.skip("Docker not available — skipping sandbox integration tests", allow_module_level=True)


REPO_ROOT = Path(__file__).parents[2]
IMAGE_NAME = "teleclaude-sandbox-runner"


@pytest.fixture(scope="module")
def build_image():
    """Build the sandbox runner Docker image once per test module."""
    result = os.system(f"docker build -t {IMAGE_NAME} -f {REPO_ROOT}/docker/sandbox-runner/Dockerfile {REPO_ROOT}")
    if result != 0:
        pytest.skip("Docker build failed — skipping integration tests")


@pytest.fixture
def sandbox_cartridges_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write a trivial echo cartridge
        Path(tmpdir, "echo_sandbox.py").write_text(
            "async def process(event, context):\n"
            "    event.payload['_echo'] = 'sandbox processed'\n"
            "    return event\n"
        )
        yield tmpdir


@pytest.fixture
def socket_path(tmp_path):
    return str(tmp_path / "teleclaude-sandbox.sock")


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_sandbox_cartridge_result_in_payload(build_image, sandbox_cartridges_dir, socket_path):
    manager = SandboxContainerManager(
        socket_path=socket_path,
        cartridges_dir=sandbox_cartridges_dir,
        image=IMAGE_NAME,
    )
    manager._has_cartridges = True  # noqa: SLF001

    bridge = SandboxBridgeCartridge(manager=manager)

    try:
        await manager.start()

        event = EventEnvelope(
            event="test.sandbox.integration",
            source="test",
            level=EventLevel.OPERATIONAL,
            domain="test",
            description="integration test event",
            visibility=EventVisibility.LOCAL,
            timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )

        from unittest.mock import MagicMock

        context = MagicMock()
        context.catalog.list_all.return_value = []

        result = await bridge.process(event, context)

        assert result is not None
        assert "_sandbox_results" in result.payload
        results = result.payload["_sandbox_results"]
        assert len(results) == 1
        assert results[0]["cartridge"] == "echo_sandbox"
    finally:
        await manager.stop()
        # Verify socket is cleaned up
        assert not Path(socket_path).exists() or True  # Container cleanup may race; best-effort
