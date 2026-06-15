"""Functional tests for workflow runner runtime config."""

from __future__ import annotations

from teleclaude.config._defaults import DEFAULT_CONFIG
from teleclaude.config._models import WorkflowConfig

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
    assert workflow["max_todo_dispatch"] == 5
