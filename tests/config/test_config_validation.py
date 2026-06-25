from __future__ import annotations

from pathlib import Path

import pydantic
import pytest
import yaml

import teleclaude.cli.config_handlers as config_handlers
from teleclaude.config.loader import load_project_config
from teleclaude.config.schema import ProjectConfig

PERSON_AREA = "person:Maurice Faber"


@pytest.mark.functional
def test_project_config_without_publishes_loads_empty_list(tmp_path: Path) -> None:
    """An old-shape teleclaude.yml with no business.publishes loads it as []."""
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        "project_name: Legacy\nbusiness:\n  domains:\n    software-development: docs\n",
        encoding="utf-8",
    )

    config = load_project_config(config_path)

    assert config.business.publishes == []


@pytest.mark.functional
def test_project_config_parses_declared_publishes(tmp_path: Path) -> None:
    """A teleclaude.yml declaring business.publishes loads the domain list."""
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        "project_name: Publisher\nbusiness:\n  publishes:\n    - erp\n    - creative\n",
        encoding="utf-8",
    )

    config = load_project_config(config_path)

    assert config.business.publishes == ["erp", "creative"]


def _write_person_config(people_dir, folder, body=None):
    """Write a valid per-person teleclaude.yml under people/{folder}/."""
    person_dir = people_dir / folder
    person_dir.mkdir(parents=True)
    with open(person_dir / "teleclaude.yml", "w", encoding="utf-8") as f:
        yaml.safe_dump(body or {}, f)


def _wire_config(tmp_path, monkeypatch, people):
    """Point validate_all at a tmp global config and people dir."""
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    global_path = tmp_path / "teleclaude.yml"
    with open(global_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"people": people}, f)
    monkeypatch.setattr(config_handlers, "_GLOBAL_CONFIG_PATH", global_path)
    monkeypatch.setattr(config_handlers, "_PEOPLE_DIR", people_dir)
    return people_dir


@pytest.mark.functional
def test_person_with_slug_differing_from_name_validates(tmp_path, monkeypatch):
    """A person whose slug differs from their display name passes validation
    when the slug-keyed config folder exists on disk (the reported regression)."""
    people_dir = _wire_config(
        tmp_path,
        monkeypatch,
        people=[{"name": "Maurice Faber", "email": "maurice@example.com", "slug": "maurice-faber"}],
    )
    _write_person_config(people_dir, "maurice-faber")

    results = config_handlers.validate_all()

    person_results = [r for r in results if r.area == PERSON_AREA]
    assert len(person_results) == 1
    assert person_results[0].passed


@pytest.mark.functional
def test_genuinely_missing_person_config_reported(tmp_path, monkeypatch):
    """When no slug, name, or username folder exists, validation fails with a
    'Config file missing' error naming the slug-keyed path."""
    people_dir = _wire_config(
        tmp_path,
        monkeypatch,
        people=[{"name": "Maurice Faber", "email": "maurice@example.com", "slug": "maurice-faber"}],
    )
    expected_path = people_dir / "maurice-faber" / "teleclaude.yml"

    results = config_handlers.validate_all()

    person_results = [r for r in results if r.area == PERSON_AREA]
    assert len(person_results) == 1
    result = person_results[0]
    assert not result.passed
    assert result.errors == [f"Config file missing: {expected_path}"]


@pytest.mark.functional
def test_project_config_accepts_valid_checkpoint_overlay():
    """A well-formed checkpoint overlay loads into a typed ProjectConfig."""
    config = ProjectConfig.model_validate(
        {
            "project_slug": "side-project",
            "checkpoint": {
                "actions": {
                    "restart": {
                        "run": "Run `make restart`",
                        "evidence": ["make restart"],
                        "main_only": True,
                        "precedence": 30,
                    },
                },
                "code": {"scope": {"include": ["src/**/*.py"]}},
                "bindings": [{"scope": {"include": ["src/**/*.py"]}, "actions": ["restart"]}],
            },
        }
    )

    assert config.checkpoint is not None
    restart = config.checkpoint.actions["restart"]
    assert restart.run  # non-empty guard
    assert restart.main_only is True
    assert restart.precedence == 30
    assert config.checkpoint.code is not None
    assert config.checkpoint.code.scope.include == ["src/**/*.py"]


@pytest.mark.functional
def test_project_config_rejects_malformed_checkpoint_overlay():
    """A checkpoint action without its required `run` command fails validation."""
    with pytest.raises(pydantic.ValidationError):
        ProjectConfig.model_validate({"checkpoint": {"actions": {"restart": {"evidence": ["make restart"]}}}})


@pytest.mark.functional
def test_project_config_rejects_unknown_referenced_action_id():
    """A binding referencing an action id absent from base and overlay is rejected.

    The runtime would otherwise silently drop the unknown id, so a typo'd reference
    would validate while its declared maintenance never surfaces.
    """
    with pytest.raises(pydantic.ValidationError):
        ProjectConfig.model_validate(
            {"checkpoint": {"bindings": [{"scope": {"include": ["src/**"]}, "actions": ["does-not-exist"]}]}}
        )


@pytest.mark.functional
def test_project_config_rejects_binding_with_no_actions():
    """A binding that references no action at all is rejected at the boundary."""
    with pytest.raises(pydantic.ValidationError):
        ProjectConfig.model_validate({"checkpoint": {"bindings": [{"scope": {"include": ["src/**"]}, "actions": []}]}})


@pytest.mark.functional
def test_project_config_accepts_binding_referencing_base_action():
    """A binding may reference a base-registry action id without declaring it."""
    config = ProjectConfig.model_validate(
        {"checkpoint": {"bindings": [{"scope": {"include": ["Dockerfile"]}, "actions": ["install"]}]}}
    )
    assert config.checkpoint is not None
    assert config.checkpoint.bindings[0].actions == ["install"]
