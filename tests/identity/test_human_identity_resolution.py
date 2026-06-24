from __future__ import annotations

import pytest
import yaml

import teleclaude.api.auth as auth
import teleclaude.config.loader as loader
import teleclaude.core.identity as identity
from teleclaude.config.schema import PersonEntry

SPEC = "project/spec/feature/identity/human-identity-resolution"

EMAIL = "maurice@instrukt.ai"
SLUG = "maurice-faber"
TELEGRAM_USER_ID = 123456


def _wire_config(tmp_path, monkeypatch, *, folder_name, person):
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    global_path = tmp_path / "teleclaude.yml"
    with open(global_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"people": [person]}, f)

    person_dir = people_dir / folder_name
    person_dir.mkdir()
    with open(person_dir / "teleclaude.yml", "w", encoding="utf-8") as f:
        yaml.safe_dump({"creds": {"telegram": {"user_name": "maurice", "user_id": TELEGRAM_USER_ID}}}, f)

    monkeypatch.setattr(loader, "GLOBAL_CONFIG_PATH", global_path)
    monkeypatch.setattr(loader, "PEOPLE_DIR", people_dir)
    monkeypatch.setattr(identity, "PEOPLE_DIR", people_dir)
    monkeypatch.setattr(identity, "_PEOPLE_DIR", people_dir)
    monkeypatch.setattr(identity, "_GLOBAL_CONFIG_PATH", global_path)
    return people_dir, person_dir


@pytest.mark.functional
@pytest.mark.spec(SPEC, "UC-HIR-PERSON-SLUG")
def test_resolved_identity_carries_person_slug_from_slug_folder(tmp_path, monkeypatch):
    _wire_config(
        tmp_path,
        monkeypatch,
        folder_name=SLUG,
        person={"name": "Maurice Faber", "email": EMAIL, "slug": SLUG},
    )

    resolver = identity.IdentityResolver()

    # Resolving by email carries the canonical slug.
    by_email = resolver.resolve_by_email(EMAIL)
    assert by_email.person_slug == SLUG

    # The per-person creds binding was loaded from the slug-named folder:
    # resolving by those telegram creds returns the same person and slug.
    by_telegram = resolver.resolve("telegram", {"user_id": TELEGRAM_USER_ID})
    assert by_telegram.person_slug == SLUG
    assert by_telegram.person_email == EMAIL


def _wire_people(tmp_path, monkeypatch, people: list[dict]) -> None:
    """Wire a global config with the given registered people list."""
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    global_path = tmp_path / "teleclaude.yml"
    with open(global_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"people": people}, f)
    monkeypatch.setattr(loader, "GLOBAL_CONFIG_PATH", global_path)
    monkeypatch.setattr(loader, "PEOPLE_DIR", people_dir)
    monkeypatch.setattr(identity, "PEOPLE_DIR", people_dir)
    monkeypatch.setattr(identity, "_PEOPLE_DIR", people_dir)
    monkeypatch.setattr(identity, "_GLOBAL_CONFIG_PATH", global_path)


@pytest.mark.functional
def test_is_multi_user_predicate_tracks_registered_people_count(tmp_path, monkeypatch):
    _wire_people(tmp_path, monkeypatch, [{"name": "Alice", "email": "alice@example.com"}])
    resolver = identity.IdentityResolver()
    monkeypatch.setattr(auth, "get_identity_resolver", lambda: resolver)

    # A sole registered person: single-user mode.
    assert resolver.is_multi_user is False
    assert auth._requires_terminal_login() == resolver.is_multi_user

    # Adding a second person flips the determination to multi-user via reload.
    global_path = tmp_path / "teleclaude.yml"
    with open(global_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {"people": [{"name": "Alice", "email": "alice@example.com"}, {"name": "Bob", "email": "bob@example.com"}]},
            f,
        )
    assert resolver.is_multi_user is True
    assert auth._requires_terminal_login() == resolver.is_multi_user


@pytest.mark.functional
def test_legacy_named_folder_still_resolves_via_fallback(tmp_path, monkeypatch):
    people_dir, person_dir = _wire_config(
        tmp_path,
        monkeypatch,
        folder_name="Maurice Faber",
        person={"name": "Maurice Faber", "email": EMAIL, "slug": SLUG},
    )
    entry = PersonEntry(name="Maurice Faber", email=EMAIL, slug=SLUG)

    # No slug-named folder exists yet; discovery falls back to the legacy name key.
    resolved = loader.find_person_config_path(entry, people_dir)
    assert resolved == person_dir / "teleclaude.yml"
