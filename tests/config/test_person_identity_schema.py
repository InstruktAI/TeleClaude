from __future__ import annotations

import json

import pytest
import yaml

import teleclaude.config.loader as loader
import teleclaude.config.migrations as migrations
from teleclaude.config.schema import PersonEntry
from teleclaude.slug import normalize_slug

SPEC = "project/spec/feature/config/person-identity-schema"


def _setup_config(tmp_path, monkeypatch, people, invitations=None):
    """Wire global config, people dir, and invitations store onto tmp_path."""
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    global_path = tmp_path / "teleclaude.yml"
    with open(global_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"people": people}, f)

    inv_path = tmp_path / "invitations.json"
    if invitations is not None:
        with open(inv_path, "w", encoding="utf-8") as f:
            json.dump(invitations, f)

    monkeypatch.setattr(loader, "GLOBAL_CONFIG_PATH", global_path)
    monkeypatch.setattr(migrations, "PEOPLE_DIR", people_dir)
    monkeypatch.setattr(loader, "PEOPLE_DIR", people_dir)
    monkeypatch.setattr("teleclaude.config.invitations.INVITATIONS_PATH", inv_path)
    monkeypatch.setattr(migrations, "_person_slug_migration_done", False)
    return people_dir, global_path, inv_path


@pytest.mark.functional
@pytest.mark.spec(SPEC, "UC-CFG-PERSON-13")
def test_well_formed_slug_accepted_and_stripped():
    canonical = "alice-smith"
    entry = PersonEntry(name="Alice Smith", email="alice@example.com", slug=f"  {canonical}  ")
    assert entry.slug == canonical


@pytest.mark.functional
@pytest.mark.spec(SPEC, "UC-CFG-PERSON-14")
def test_empty_or_absent_slug_normalizes_to_none():
    omitted = PersonEntry(name="Alice", email="alice@example.com")
    empty = PersonEntry(name="Bob", email="bob@example.com", slug="")
    whitespace = PersonEntry(name="Carol", email="carol@example.com", slug="   ")
    assert omitted.slug is None
    assert empty.slug is None
    assert whitespace.slug is None


@pytest.mark.functional
@pytest.mark.spec(SPEC, "UC-CFG-PERSON-15")
def test_invalid_slug_format_rejected():
    with pytest.raises(ValueError, match="Invalid slug"):
        PersonEntry(name="Alice", email="alice@example.com", slug="Alice_Smith")


@pytest.mark.functional
@pytest.mark.spec(SPEC, "UC-CFG-PERSON-16")
def test_legacy_person_migrated_with_folder_and_invitation_remap(tmp_path, monkeypatch):
    people_dir, _global_path, inv_path = _setup_config(
        tmp_path,
        monkeypatch,
        people=[{"name": "Alice Smith", "email": "alice@example.com"}],
        invitations={"inv_legacy": "Alice Smith"},
    )
    expected_slug = normalize_slug("Alice Smith")
    legacy_dir = people_dir / "Alice Smith"
    legacy_dir.mkdir()
    (legacy_dir / "teleclaude.yml").write_text("interests: []\n", encoding="utf-8")

    migrations.migrate_person_slugs_if_needed()

    config = loader.load_global_config()
    assert config.people[0].slug == expected_slug
    assert (people_dir / expected_slug / "teleclaude.yml").exists()
    assert not legacy_dir.exists()
    with open(inv_path, encoding="utf-8") as f:
        assert json.load(f) == {"inv_legacy": expected_slug}

    # Second run is a no-op (idempotent): folder and slug unchanged.
    monkeypatch.setattr(migrations, "_person_slug_migration_done", False)
    migrations.migrate_person_slugs_if_needed()
    assert loader.load_global_config().people[0].slug == expected_slug
    assert (people_dir / expected_slug / "teleclaude.yml").exists()


@pytest.mark.functional
def test_colliding_names_get_distinct_slugs_without_folders(tmp_path, monkeypatch):
    base = normalize_slug("Alice Smith")
    preassigned = f"{base}-2"
    _setup_config(
        tmp_path,
        monkeypatch,
        people=[
            {"name": "Alice Smith", "email": "alice1@example.com"},
            {"name": "Alice  Smith", "email": "alice2@example.com"},
            {"name": "Bob", "email": "bob@example.com", "slug": preassigned},
        ],
    )

    migrations.migrate_person_slugs_if_needed()

    people = loader.load_global_config().people
    slugs = [p.slug for p in people]
    assert len(set(slugs)) == len(slugs)
    assert base in slugs
    assert people[2].slug == preassigned
