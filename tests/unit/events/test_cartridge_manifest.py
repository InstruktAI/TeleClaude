"""Characterization tests for teleclaude.events.cartridge_manifest."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from teleclaude.events.cartridge_manifest import (
    CartridgeCycleError,
    CartridgeDependencyError,
    CartridgeError,
    CartridgeManifest,
    CartridgeScopeError,
)


def test_manifest_requires_id_and_description() -> None:
    with pytest.raises(ValidationError):
        CartridgeManifest.model_validate({})


def test_manifest_minimal_valid() -> None:
    m = CartridgeManifest.model_validate({"id": "test", "description": "desc"})
    assert m.id == "test"
    assert m.description == "desc"


def test_manifest_version_default() -> None:
    m = CartridgeManifest.model_validate({"id": "a", "description": "b"})
    assert m.version == "0.1.0"


def test_manifest_lists_default_empty() -> None:
    m = CartridgeManifest.model_validate({"id": "a", "description": "b"})
    assert m.domain_affinity == []
    assert m.depends_on == []
    assert m.output_slots == []


def test_manifest_personal_default_false() -> None:
    m = CartridgeManifest.model_validate({"id": "a", "description": "b"})
    assert m.personal is False


def test_manifest_module_default() -> None:
    m = CartridgeManifest.model_validate({"id": "a", "description": "b"})
    assert m.module == "cartridge"


def test_manifest_extra_fields_allowed() -> None:
    m = CartridgeManifest.model_validate({"id": "a", "description": "b", "custom_key": "val"})
    assert m.model_extra is not None
    assert m.model_extra.get("custom_key") == "val"


def test_manifest_full_fields() -> None:
    raw = {
        "id": "my-cartridge",
        "description": "does stuff",
        "version": "1.2.3",
        "domain_affinity": ["eng"],
        "depends_on": ["other"],
        "output_slots": ["slot.a"],
        "personal": True,
        "module": "my_module",
    }
    m = CartridgeManifest.model_validate(raw)
    assert m.version == "1.2.3"
    assert m.domain_affinity == ["eng"]
    assert m.depends_on == ["other"]
    assert m.output_slots == ["slot.a"]
    assert m.personal is True
    assert m.module == "my_module"


def test_cartridge_error_is_base_exception() -> None:
    e = CartridgeError("base")
    assert isinstance(e, Exception)


def test_cartridge_cycle_error_inherits_cartridge_error() -> None:
    e = CartridgeCycleError("cycle")
    assert isinstance(e, CartridgeError)


def test_cartridge_dependency_error_inherits_cartridge_error() -> None:
    e = CartridgeDependencyError("dep")
    assert isinstance(e, CartridgeError)


def test_cartridge_scope_error_inherits_cartridge_error() -> None:
    e = CartridgeScopeError("scope")
    assert isinstance(e, CartridgeError)
