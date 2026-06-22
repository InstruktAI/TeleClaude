from __future__ import annotations

from ruamel.yaml import YAML

import teleclaude.cli.config_handlers as handlers
from teleclaude.cli.config_handlers import (
    find_person_by_invite_token,
    get_person_config,
    save_person_config,
    set_invite_token,
)
from teleclaude.config.invitations import load_invitations
from teleclaude.config.schema import PersonConfig

INV_PREFIX = "inv_"


def test_invitation_generation_and_redemption(tmp_path, monkeypatch):
    inv_path = tmp_path / "invitations.json"
    people_dir = tmp_path / "people"
    people_dir.mkdir()

    monkeypatch.setattr(handlers, "_PEOPLE_DIR", people_dir)
    monkeypatch.setattr("teleclaude.config.loader.PEOPLE_DIR", people_dir)
    monkeypatch.setattr(handlers, "list_person_dirs", lambda: [d.name for d in people_dir.iterdir() if d.is_dir()])

    monkeypatch.setattr("teleclaude.config.invitations.INVITATIONS_PATH", inv_path)
    monkeypatch.setattr("teleclaude.cli.config_handlers.INVITATIONS_PATH", inv_path)
    monkeypatch.setattr("teleclaude.paths.INVITATIONS_PATH", inv_path)

    # 1. Add a person keyed by slug
    slug = "john-doe"
    person_dir = people_dir / slug
    person_dir.mkdir()
    person_config = PersonConfig()
    save_person_config(slug, person_config)

    # 2. Generate/set invite token
    token = set_invite_token(slug)
    assert token.startswith(INV_PREFIX)

    # Verify stored in invitations.json mapped to the slug
    invitations = load_invitations()
    assert invitations == {token: slug}

    # Verify NOT in person config model_extra
    pc = get_person_config(slug)
    assert pc.model_extra is None or "invite_token" not in pc.model_extra

    # 3. Redeem/find by token returns the slug
    result = find_person_by_invite_token(token)
    assert result is not None
    found_slug, found_config = result
    assert found_slug == slug
    assert isinstance(found_config, PersonConfig)

    # 4. Rotate token
    new_token = set_invite_token(slug)
    assert new_token != token
    assert new_token.startswith(INV_PREFIX)

    # Verify old token removed and new token added
    invitations = load_invitations()
    assert token not in invitations
    assert invitations == {new_token: slug}

    # Verify redemption of old token fails, new token succeeds
    assert find_person_by_invite_token(token) is None
    assert find_person_by_invite_token(new_token)[0] == slug


def test_invitation_migration(tmp_path, monkeypatch):
    inv_path = tmp_path / "invitations.json"
    people_dir = tmp_path / "people"
    people_dir.mkdir()

    monkeypatch.setattr(handlers, "_PEOPLE_DIR", people_dir)
    monkeypatch.setattr("teleclaude.config.loader.PEOPLE_DIR", people_dir)
    monkeypatch.setattr(handlers, "list_person_dirs", lambda: [d.name for d in people_dir.iterdir() if d.is_dir()])

    # Make sure _migration_done is reset
    monkeypatch.setattr(handlers, "_migration_done", False)

    monkeypatch.setattr("teleclaude.config.invitations.INVITATIONS_PATH", inv_path)
    monkeypatch.setattr("teleclaude.cli.config_handlers.INVITATIONS_PATH", inv_path)
    monkeypatch.setattr("teleclaude.paths.INVITATIONS_PATH", inv_path)

    # 1. Simulate legacy person with invite_token inside the YAML file, folder keyed by slug
    slug = "legacy-user"
    person_dir = people_dir / slug
    person_dir.mkdir()
    yaml_file = person_dir / "teleclaude.yml"

    yaml = YAML()
    legacy_data = {"interests": [], "invite_token": "inv_legacy123"}
    with open(yaml_file, "w", encoding="utf-8") as f:
        yaml.dump(legacy_data, f)

    # Verify that before first store access, invitations.json does not exist
    assert not inv_path.exists()

    # 2. Trigger first store access migration by calling find_person_by_invite_token
    result = find_person_by_invite_token("inv_legacy123")
    assert result is not None
    assert result[0] == slug

    # Verify invitations.json was created and contains the legacy token mapping to the slug
    assert inv_path.exists()
    invitations = load_invitations()
    assert invitations == {"inv_legacy123": slug}

    # Verify invite_token was removed from the person config file
    with open(yaml_file, encoding="utf-8") as f:
        saved_data = yaml.load(f) or {}
    assert "invite_token" not in saved_data
