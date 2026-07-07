"""Slug-exposure coverage for ``telec config people list``.

The people-listing surface exposes each person's slug so an agent can
discover the identifier ``telec message`` addresses
(``project/spec/messaging`` Discovery clause). No feature spec exists for
this command-surface-refinement todo (Category B), so this test carries no
``@pytest.mark.spec`` marker.
"""

from __future__ import annotations

import json

import pytest

import teleclaude.cli.config_cli as config_cli
from teleclaude.config.schema import PersonConfig, PersonEntry

_NAME = "Alex"
_SLUG = "alex"
_ROLE = "member"
_EMAIL = "alex@example.com"


def _person() -> PersonEntry:
    return PersonEntry(name=_NAME, email=_EMAIL, slug=_SLUG, role=_ROLE)


def test_text_listing_includes_the_slug(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(config_cli, "list_people", lambda: [_person()])

    config_cli._people_list(use_json=False)

    out = capsys.readouterr().out
    assert f"[{_SLUG}]" in out


def test_json_listing_includes_the_slug(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(config_cli, "list_people", lambda: [_person()])
    monkeypatch.setattr(config_cli, "get_person_config", lambda _slug: PersonConfig())

    config_cli._people_list(use_json=True)

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data[0]["slug"] == _SLUG


def test_text_listing_omits_slug_bracket_when_person_has_no_slug(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    person_without_slug = PersonEntry(name=_NAME, email=_EMAIL, slug=None, role=_ROLE)
    monkeypatch.setattr(config_cli, "list_people", lambda: [person_without_slug])

    config_cli._people_list(use_json=False)

    out = capsys.readouterr().out
    assert "[" not in out
