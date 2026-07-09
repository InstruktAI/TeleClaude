"""Functional tests for the job-runner role's CLI command clearance.

A job-runner session's lineage privilege is narrow — the only role permitted a
no-human root at todo/bug creation (project/spec/domain/workflow). Its CLI
clearance must be scoped to match: exactly the create verbs that privilege
serves, never the broad system clearance every dispatch-capable role shares.
"""

from __future__ import annotations

import pytest

from teleclaude.cli.telec import is_command_allowed
from teleclaude.constants import ROLE_JOB_RUNNER

pytestmark = pytest.mark.functional


@pytest.mark.parametrize("command", ["telec todo create", "telec bugs report"])
def test_job_runner_is_cleared_for_its_create_verbs(command: str) -> None:
    assert is_command_allowed(command, ROLE_JOB_RUNNER, None) is True


@pytest.mark.parametrize(
    "command",
    [
        "telec sessions send",
        "telec sessions restart",
        "telec agents status",
        "telec channels publish",
        "telec message",
    ],
)
def test_job_runner_is_denied_broad_system_clearance(command: str) -> None:
    assert is_command_allowed(command, ROLE_JOB_RUNNER, None) is False
