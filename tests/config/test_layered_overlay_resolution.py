from __future__ import annotations

import pytest

import teleclaude.config.loader as loader

SPEC = "project/spec/feature/config/layered-overlay-resolution"
CHIP_COLOR_SPEC = "project/spec/feature/config/person-chip-color"


def _load_person_overlay(tmp_path, monkeypatch, overlay_yaml: str):
    """Load a person workspace overlay through the real YAML→config path."""
    home = tmp_path / ".teleclaude"
    slug_dir = home / "people" / "alice-smith"
    slug_dir.mkdir(parents=True)
    (home / "teleclaude.yml").write_text("people: []\n", encoding="utf-8")
    (slug_dir / "teleclaude.yml").write_text(overlay_yaml, encoding="utf-8")
    monkeypatch.setattr(loader, "GLOBAL_CONFIG_PATH", home / "teleclaude.yml")
    app_config = loader.load_app_config(slug_dir)
    assert app_config.person is not None
    return app_config.person


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


@pytest.mark.functional
@pytest.mark.spec(SPEC, "UC-CFG-OVERLAY-2")
def test_member_project_workspace_composes_project_plus_company(tmp_path, monkeypatch):
    home = tmp_path / ".teleclaude"
    home.mkdir(parents=True)
    (home / "teleclaude.yml").write_text("people: []\n", encoding="utf-8")

    company_slug = "instrukt-ai"
    company_dir = home / "companies" / company_slug
    company_dir.mkdir(parents=True)
    (company_dir / "teleclaude.yml").write_text(
        f"name: Instrukt AI\nslug: {company_slug}\ndescription: AI orphanage\n", encoding="utf-8"
    )

    project_root = tmp_path / "web"
    project_root.mkdir()
    (project_root / "teleclaude.yml").write_text(f"project_slug: web\ncompany: {company_slug}\n", encoding="utf-8")

    monkeypatch.setattr(loader, "GLOBAL_CONFIG_PATH", home / "teleclaude.yml")
    monkeypatch.setattr(loader, "COMPANIES_ROOT", home / "companies")

    app_config = loader.load_app_config(project_root)

    # The company composes alongside the project (both present at once), resolved
    # from the project's company membership.
    assert app_config.project is not None
    assert app_config.company is not None
    assert app_config.company.slug == company_slug


@pytest.mark.functional
@pytest.mark.spec(SPEC, "UC-CFG-OVERLAY-2")
def test_project_without_company_leaves_company_layer_none(tmp_path, monkeypatch):
    home = tmp_path / ".teleclaude"
    home.mkdir(parents=True)
    (home / "teleclaude.yml").write_text("people: []\n", encoding="utf-8")

    project_root = tmp_path / "web"
    project_root.mkdir()
    (project_root / "teleclaude.yml").write_text("project_slug: web\n", encoding="utf-8")

    monkeypatch.setattr(loader, "GLOBAL_CONFIG_PATH", home / "teleclaude.yml")
    monkeypatch.setattr(loader, "COMPANIES_ROOT", home / "companies")

    app_config = loader.load_app_config(project_root)

    assert app_config.project is not None
    assert app_config.company is None


@pytest.mark.functional
@pytest.mark.spec(CHIP_COLOR_SPEC, "UC-CHIP-COLOR-1")
def test_person_overlay_without_color_resolves_color_none(tmp_path, monkeypatch):
    person = _load_person_overlay(tmp_path, monkeypatch, "interests:\n  - coding\n")

    assert person.color is None


@pytest.mark.functional
@pytest.mark.spec(CHIP_COLOR_SPEC, "UC-CHIP-COLOR-2")
def test_person_overlay_single_color_cell_sets_without_siblings(tmp_path, monkeypatch):
    background_light = "#abcdef"
    person = _load_person_overlay(
        tmp_path,
        monkeypatch,
        f"color:\n  background:\n    light: '{background_light}'\n",
    )

    assert person.color is not None
    # Round-trip identity: the one cell provided survives, siblings stay unset.
    assert person.color.background.light == background_light
    assert person.color.background.dark is None
    assert person.color.text.light is None
    assert person.color.text.dark is None


@pytest.mark.functional
@pytest.mark.spec(CHIP_COLOR_SPEC, "UC-CHIP-COLOR-4")
def test_person_overlay_set_color_cell_stored_verbatim(tmp_path, monkeypatch):
    text_dark = "bright_white"
    person = _load_person_overlay(
        tmp_path,
        monkeypatch,
        f"color:\n  text:\n    dark: '{text_dark}'\n",
    )

    assert person.color is not None
    # The stored value equals the provided input, unchanged.
    assert person.color.text.dark == text_dark
