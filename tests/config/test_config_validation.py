from __future__ import annotations

import pytest
import yaml

import teleclaude.cli.config_handlers as config_handlers

PERSON_AREA = "person:Maurice Faber"


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
