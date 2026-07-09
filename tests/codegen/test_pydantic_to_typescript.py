"""Functional tests for the Pydantic-to-TypeScript generator."""

from __future__ import annotations

import pytest

from teleclaude.codegen.pydantic_to_typescript import generate

pytestmark = pytest.mark.functional


def test_generate_renders_the_full_api_models_surface_without_raising() -> None:
    """The generator renders every discovered model, including enum-typed fields."""
    output = generate()

    assert output.strip() != ""
