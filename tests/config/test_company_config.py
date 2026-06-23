from __future__ import annotations

import pytest
from pydantic import ValidationError

from teleclaude.config.schema import CompanyConfig, ProjectConfig

_COMPANY_SLUG = "instrukt-ai"
_COMPANY_NAME = "Instrukt AI"
_OWNER_SLUG = "maurice-faber"
_PROJECT_SLUG = "web"


@pytest.mark.functional
def test_company_config_accepts_minimal_profile():
    """A minimal company (name + slug) is valid; optional fields default to None."""
    config = CompanyConfig(name=_COMPANY_NAME, slug=_COMPANY_SLUG)
    assert config.slug == _COMPANY_SLUG
    assert config.erp_id is None


@pytest.mark.functional
def test_company_config_accepts_owner_by_person_slug():
    """The owner references a person by ``PersonConfig.slug``."""
    config = CompanyConfig(name=_COMPANY_NAME, slug=_COMPANY_SLUG, owner=_OWNER_SLUG)
    assert config.owner == _OWNER_SLUG


@pytest.mark.functional
def test_company_config_rejects_malformed_slug():
    """A malformed company slug is rejected at the model boundary."""
    with pytest.raises(ValidationError):
        CompanyConfig(name=_COMPANY_NAME, slug="Instrukt AI")


@pytest.mark.functional
def test_company_config_rejects_malformed_owner():
    """A malformed owner slug is rejected at the model boundary."""
    with pytest.raises(ValidationError):
        CompanyConfig(name=_COMPANY_NAME, slug=_COMPANY_SLUG, owner="Maurice Faber")


@pytest.mark.functional
def test_project_company_accepts_kebab_slug():
    """A project may declare an at-most-one kebab-case company membership."""
    config = ProjectConfig(project_slug=_PROJECT_SLUG, company=_COMPANY_SLUG)
    assert config.company == _COMPANY_SLUG


@pytest.mark.functional
def test_project_company_absent_is_valid():
    """A project under no company umbrella is valid; company resolves to None."""
    config = ProjectConfig(project_slug=_PROJECT_SLUG)
    assert config.company is None


@pytest.mark.functional
def test_project_company_blank_normalizes_to_none():
    """A blank company value normalizes to None rather than an empty membership."""
    config = ProjectConfig(project_slug=_PROJECT_SLUG, company="   ")
    assert config.company is None


@pytest.mark.functional
def test_project_company_rejects_malformed_slug():
    """A malformed company slug is rejected rather than silently accepted."""
    with pytest.raises(ValidationError):
        ProjectConfig(project_slug=_PROJECT_SLUG, company="Instrukt AI")
