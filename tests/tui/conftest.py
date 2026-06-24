"""Shared TUI test fixtures."""

from __future__ import annotations

from collections.abc import Callable

import pytest
import yaml

import teleclaude.cli.tui.widgets.chip as chip
import teleclaude.config.loader as loader
import teleclaude.core.identity as identity


@pytest.fixture
def wire_people(tmp_path, monkeypatch) -> Callable[..., identity.IdentityResolver]:
    """Wire a real IdentityResolver over a temp global config + person overlays.

    Returns a builder that registers the given people (and optional per-person
    overlay YAML keyed by folder slug), constructs a resolver against them, and
    points the chip helper's resolver lookup at it. Drives the real
    YAML→config→resolver path that the chip renderer consumes.
    """

    def _wire(people: list[dict], *, overlays: dict[str, str] | None = None) -> identity.IdentityResolver:
        people_dir = tmp_path / "people"
        people_dir.mkdir(exist_ok=True)
        global_path = tmp_path / "teleclaude.yml"
        with open(global_path, "w", encoding="utf-8") as f:
            yaml.safe_dump({"people": people}, f)
        for slug, overlay_yaml in (overlays or {}).items():
            person_dir = people_dir / slug
            person_dir.mkdir(parents=True, exist_ok=True)
            (person_dir / "teleclaude.yml").write_text(overlay_yaml, encoding="utf-8")

        monkeypatch.setattr(loader, "GLOBAL_CONFIG_PATH", global_path)
        monkeypatch.setattr(loader, "PEOPLE_DIR", people_dir)
        monkeypatch.setattr(identity, "PEOPLE_DIR", people_dir)
        monkeypatch.setattr(identity, "_PEOPLE_DIR", people_dir)
        monkeypatch.setattr(identity, "_GLOBAL_CONFIG_PATH", global_path)

        resolver = identity.IdentityResolver()
        monkeypatch.setattr(chip, "get_identity_resolver", lambda: resolver)
        return resolver

    return _wire
