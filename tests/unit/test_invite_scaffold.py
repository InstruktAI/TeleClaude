"""Tests for scaffold_personal_workspace in invite.py."""

import pytest

from teleclaude import invite


@pytest.fixture
def mock_people_dir(tmp_path, monkeypatch):
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    monkeypatch.setattr(invite, "_PEOPLE_DIR", people_dir)
    return people_dir


def test_scaffold_returns_person_folder_not_workspace_subfolder(mock_people_dir):
    result = invite.scaffold_personal_workspace("alice")
    assert result == mock_people_dir / "alice"
    assert "workspace" not in result.parts


def test_scaffold_creates_person_folder(mock_people_dir):
    result = invite.scaffold_personal_workspace("alice")
    assert result.is_dir()


def test_scaffold_creates_default_agents_master_when_absent(mock_people_dir):
    result = invite.scaffold_personal_workspace("alice")
    agents_master = result / "AGENTS.master.md"
    assert agents_master.exists()
    assert "alice" in agents_master.read_text()


def test_scaffold_does_not_overwrite_existing_agents_master(mock_people_dir):
    person_dir = mock_people_dir / "bob"
    person_dir.mkdir()
    existing = person_dir / "AGENTS.master.md"
    existing.write_text("custom content", encoding="utf-8")

    invite.scaffold_personal_workspace("bob")

    assert existing.read_text() == "custom content"


def test_scaffold_creates_teleclaude_yml(mock_people_dir):
    result = invite.scaffold_personal_workspace("alice")
    assert (result / "teleclaude.yml").exists()


def test_scaffold_does_not_create_workspace_subfolder(mock_people_dir):
    invite.scaffold_personal_workspace("alice")
    assert not (mock_people_dir / "alice" / "workspace").exists()
