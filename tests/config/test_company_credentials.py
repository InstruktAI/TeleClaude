from __future__ import annotations

import os
from pathlib import Path

import pytest

from teleclaude.config.loader import CompanyCredentialsError, load_company_credentials

_SLUG = "instrukt-ai"
_TOKEN_KEY = "API_TOKEN"
_TOKEN_VALUE = "secret-123"


def _write_company_env(companies_root: Path, slug: str, body: str, *, mode: int = 0o600) -> Path:
    """Create ``companies/<slug>/.env`` with the given body and permission mode."""
    company_dir = companies_root / slug
    company_dir.mkdir(parents=True, exist_ok=True)
    env_path = company_dir / ".env"
    env_path.write_text(body, encoding="utf-8")
    os.chmod(env_path, mode)
    return env_path


@pytest.mark.functional
def test_company_credential_resolves_through_seam(tmp_path):
    """A credential resolves from the company ``.env`` via the resolver seam, keyed by slug alone."""
    companies_root = tmp_path / "companies"
    _write_company_env(companies_root, _SLUG, f"{_TOKEN_KEY}={_TOKEN_VALUE}\n")

    creds = load_company_credentials(_SLUG, companies_root)

    assert creds[_TOKEN_KEY] == _TOKEN_VALUE


@pytest.mark.functional
def test_company_credential_expands_var_reference(tmp_path, monkeypatch):
    """A ``${VAR}`` reference in the company ``.env`` resolves through the existing mechanism."""
    outer_value = "from-environment"
    monkeypatch.setenv("OUTER_SECRET", outer_value)
    companies_root = tmp_path / "companies"
    _write_company_env(companies_root, _SLUG, f"{_TOKEN_KEY}=${{OUTER_SECRET}}\n")

    creds = load_company_credentials(_SLUG, companies_root)

    assert creds[_TOKEN_KEY] == outer_value


@pytest.mark.functional
def test_missing_company_env_returns_empty(tmp_path):
    """A company with no ``.env`` has no credentials — a typed empty result, not a crash."""
    companies_root = tmp_path / "companies"
    (companies_root / _SLUG).mkdir(parents=True)

    creds = load_company_credentials(_SLUG, companies_root)

    assert creds == {}


@pytest.mark.functional
def test_world_readable_company_env_rejected(tmp_path):
    """A group/world-readable ``.env`` exposes secrets and is rejected loudly."""
    companies_root = tmp_path / "companies"
    _write_company_env(companies_root, _SLUG, f"{_TOKEN_KEY}={_TOKEN_VALUE}\n", mode=0o644)

    with pytest.raises(CompanyCredentialsError):
        load_company_credentials(_SLUG, companies_root)


@pytest.mark.functional
def test_unreadable_company_env_raises(tmp_path):
    """An unreadable ``.env`` raises rather than silently returning empty credentials."""
    companies_root = tmp_path / "companies"
    _write_company_env(companies_root, _SLUG, f"{_TOKEN_KEY}={_TOKEN_VALUE}\n", mode=0o000)

    with pytest.raises(CompanyCredentialsError):
        load_company_credentials(_SLUG, companies_root)


@pytest.mark.functional
def test_malformed_slug_rejected_before_path_construction(tmp_path):
    """A path-traversal/malformed slug is rejected by the slug validator, never resolving a path."""
    companies_root = tmp_path / "companies"
    with pytest.raises(ValueError, match="Invalid slug"):
        load_company_credentials("../../etc", companies_root)
