"""Functional tests for workflow runner project config."""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from teleclaude.config.loader import load_project_config
from teleclaude.config.schema import ProjectConfig

DEFAULT_AUTOSTART = {"feature": True, "change": True, "bug": True, "task": False}
WORKFLOW_CONFIG_REF = "#/$defs/WorkflowConfig"
WORKFLOW_AUTOSTART_CONFIG_REF = "#/$defs/WorkflowAutostartConfig"
JSON_SCHEMA_BOOLEAN = "boolean"


def test_project_config_loads_workflow_autostart_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "teleclaude.yml"
    YAML().dump({"project_slug": "runner-config"}, config_path)

    config = load_project_config(config_path)

    assert config.workflow.autostart.model_dump() == DEFAULT_AUTOSTART


def test_project_config_loads_workflow_autostart_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "teleclaude.yml"
    YAML().dump(
        {
            "project_slug": "runner-config",
            "workflow": {"autostart": {"feature": False, "change": False, "bug": True, "task": True}},
        },
        config_path,
    )

    config = load_project_config(config_path)

    assert config.workflow.autostart.feature is False
    assert config.workflow.autostart.change is False
    assert config.workflow.autostart.bug is True
    assert config.workflow.autostart.task is True


def test_schema_export_includes_workflow_autostart_group() -> None:
    schema = ProjectConfig.model_json_schema()

    workflow = schema["properties"]["workflow"]
    assert workflow["$ref"] == WORKFLOW_CONFIG_REF
    workflow_def = schema["$defs"]["WorkflowConfig"]
    autostart = workflow_def["properties"]["autostart"]
    assert autostart["$ref"] == WORKFLOW_AUTOSTART_CONFIG_REF
    autostart_def = schema["$defs"]["WorkflowAutostartConfig"]
    properties = autostart_def["properties"]
    assert set(properties) == set(DEFAULT_AUTOSTART)
    for key, default in DEFAULT_AUTOSTART.items():
        field = properties[key]
        assert field["type"] == JSON_SCHEMA_BOOLEAN
        assert field["default"] is default
