from __future__ import annotations

import pytest

import teleclaude.config.loader as loader

SPEC = "project/spec/feature/config/layered-overlay-resolution"


@pytest.mark.functional
@pytest.mark.spec(SPEC, "UC-CFG-OVERLAY-2")
def test_person_workspace_composes_global_plus_per_person(tmp_path, monkeypatch):
    home = tmp_path / ".teleclaude"
    slug_dir = home / "people" / "alice-smith"
    slug_dir.mkdir(parents=True)
    (home / "teleclaude.yml").write_text("people: []\n", encoding="utf-8")
    (slug_dir / "teleclaude.yml").write_text("interests:\n  - coding\n", encoding="utf-8")

    monkeypatch.setattr(loader, "GLOBAL_CONFIG_PATH", home / "teleclaude.yml")

    app_config = loader.load_app_config(slug_dir)

    # Detected as a person workspace: per-person overlay read from the slug folder,
    # project layer left None, global overlay present.
    assert app_config.person is not None
    assert app_config.project is None
    assert app_config.global_ is not None
