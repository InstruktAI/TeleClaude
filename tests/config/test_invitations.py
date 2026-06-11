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
    monkeypatch.setattr(handlers, "list_person_dirs", lambda: [d.name for d in people_dir.iterdir() if d.is_dir()])

    monkeypatch.setattr("teleclaude.config.invitations.INVITATIONS_PATH", inv_path)
    monkeypatch.setattr("teleclaude.cli.config_handlers.INVITATIONS_PATH", inv_path)
    monkeypatch.setattr("teleclaude.paths.INVITATIONS_PATH", inv_path)

    # 1. Add a person
    name = "John Doe"
    person_dir = people_dir / name
    person_dir.mkdir()
    person_config = PersonConfig()
    save_person_config(name, person_config)

    # 2. Generate/set invite token
    token = set_invite_token(name)
    assert token.startswith(INV_PREFIX)

    # Verify stored in invitations.json
    invitations = load_invitations()
    assert invitations == {token: name}

    # Verify NOT in person config model_extra
    pc = get_person_config(name)
    assert pc.model_extra is None or "invite_token" not in pc.model_extra

    # 3. Redeem/find by token
    result = find_person_by_invite_token(token)
    assert result is not None
    found_name, found_config = result
    assert found_name == name
    assert isinstance(found_config, PersonConfig)

    # 4. Rotate token
    new_token = set_invite_token(name)
    assert new_token != token
    assert new_token.startswith(INV_PREFIX)

    # Verify old token removed and new token added
    invitations = load_invitations()
    assert token not in invitations
    assert invitations == {new_token: name}

    # Verify redemption of old token fails, new token succeeds
    assert find_person_by_invite_token(token) is None
    assert find_person_by_invite_token(new_token)[0] == name


def test_invitation_migration(tmp_path, monkeypatch):
    inv_path = tmp_path / "invitations.json"
    people_dir = tmp_path / "people"
    people_dir.mkdir()

    monkeypatch.setattr(handlers, "_PEOPLE_DIR", people_dir)
    monkeypatch.setattr(handlers, "list_person_dirs", lambda: [d.name for d in people_dir.iterdir() if d.is_dir()])

    # Make sure _migration_done is reset
    monkeypatch.setattr(handlers, "_migration_done", False)

    monkeypatch.setattr("teleclaude.config.invitations.INVITATIONS_PATH", inv_path)
    monkeypatch.setattr("teleclaude.cli.config_handlers.INVITATIONS_PATH", inv_path)
    monkeypatch.setattr("teleclaude.paths.INVITATIONS_PATH", inv_path)

    # 1. Simulate legacy person with invite_token inside the YAML file
    name = "Legacy User"
    person_dir = people_dir / name
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
    assert result[0] == name

    # Verify invitations.json was created and contains the legacy token mapping
    assert inv_path.exists()
    invitations = load_invitations()
    assert invitations == {"inv_legacy123": name}

    # Verify invite_token was removed from the person config file
    with open(yaml_file, encoding="utf-8") as f:
        saved_data = yaml.load(f) or {}
    assert "invite_token" not in saved_data
