"""Functional tests for workflow runner runtime config."""

from __future__ import annotations

import pytest

from teleclaude.config import _parse_workflow_config
from teleclaude.config._defaults import DEFAULT_CONFIG
from teleclaude.config._models import WorkflowConfig, WorkflowRunnerMode

ALL_FALSE_AUTOSTART = {"feature": False, "change": False, "bug": False, "task": False}


def test_workflow_config_defaults_all_autostart_off() -> None:
    workflow = WorkflowConfig()

    assert workflow.autostart.feature is False
    assert workflow.autostart.change is False
    assert workflow.autostart.bug is False
    assert workflow.autostart.task is False


def test_workflow_config_default_max_todo_dispatch_is_five() -> None:
    assert WorkflowConfig().max_todo_dispatch == 5


def test_default_config_blueprint_ships_all_autostart_off() -> None:
    workflow = DEFAULT_CONFIG["workflow"]

    assert isinstance(workflow, dict)
    assert workflow["autostart"] == ALL_FALSE_AUTOSTART
    assert workflow["runner"] == WorkflowRunnerMode.AUTOSTART.value
    assert workflow["max_todo_dispatch"] == 5


def test_parse_workflow_config_defaults_runner_to_autostart() -> None:
    """An unconfigured machine (no `runner` key) stays on autostart."""
    parsed = _parse_workflow_config({"autostart": ALL_FALSE_AUTOSTART})

    assert parsed.runner is WorkflowRunnerMode.AUTOSTART


def test_parse_workflow_config_accepts_manual_runner() -> None:
    parsed = _parse_workflow_config({"runner": "manual"})

    assert parsed.runner is WorkflowRunnerMode.MANUAL


def test_parse_workflow_config_rejects_unknown_runner() -> None:
    with pytest.raises(ValueError):
        _parse_workflow_config({"runner": "bogus"})
