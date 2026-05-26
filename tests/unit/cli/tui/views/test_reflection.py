"""Unit tests for generic schema reflection and deserialization engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

import pytest
from pydantic import BaseModel, Field

from teleclaude.cli.tui.views.reflection import (
    ReflectedField,
    deserialize_value,
    reflect_schema,
    resolve_env_placeholders,
)

EXPECTED_PYDANTIC_KEYS = {"name", "count", "mode", "choices", "sub.enabled", "sub.token"}
BLACKLISTED_KEY = "sub.announcements_channel_id"
EXPECTED_DATACLASS_KEYS = {"title", "is_active", "priority"}
NAME_DEFAULT = "Test"
NAME_DESCRIPTION = "Name of the model"


class MockEnum(str, Enum):
    ALPHA = "alpha"
    BETA = "beta"


class MockSubModel(BaseModel):
    enabled: bool = True
    token: str = "secret"
    announcements_channel_id: int = 123456  # Should be blacklisted


class MockModel(BaseModel):
    name: str = Field(default="Test", description="Name of the model")
    count: int = 42
    mode: MockEnum = MockEnum.ALPHA
    choices: Literal["yes", "no"] = "yes"
    sub: MockSubModel = Field(default_factory=MockSubModel)


@dataclass
class MockDataclass:
    title: str
    is_active: bool
    priority: list[str]


def test_reflect_pydantic_base_model() -> None:
    """It dynamically extracts fields from a Pydantic model."""
    model = MockModel()
    fields = reflect_schema(model)

    keys = {f.key for f in fields}
    assert EXPECTED_PYDANTIC_KEYS.issubset(keys)
    # Blacklisted fields are reflected away
    assert BLACKLISTED_KEY not in keys

    # Verify field values and descriptions
    name_field = next(f for f in fields if f.key == "name")
    assert name_field.value == NAME_DEFAULT
    assert name_field.description == NAME_DESCRIPTION
    assert name_field.field_type is str

    choices_field = next(f for f in fields if f.key == "choices")
    assert choices_field.choices == ["yes", "no"]
    assert choices_field.field_type is Literal


def test_reflect_dataclass() -> None:
    """It dynamically extracts fields from a standard dataclass."""
    dc = MockDataclass(title="Dc", is_active=True, priority=["a", "b"])
    fields = reflect_schema(dc)

    keys = {f.key for f in fields}
    assert EXPECTED_DATACLASS_KEYS.issubset(keys)

    priority_field = next(f for f in fields if f.key == "priority")
    assert priority_field.value == ["a", "b"]
    assert priority_field.field_type == list[str]


SECRET_VAR = "DISCORD_BOT_TOKEN"
SECRET_VALUE = "secret-123"
LITERAL_LANG = "en_US"


def test_resolve_env_placeholder_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ${VAR} field value resolves to the env value and records the backing variable."""
    monkeypatch.setenv(SECRET_VAR, SECRET_VALUE)
    field = ReflectedField(key="discord.token", name="Token", field_type=str, value=f"${{{SECRET_VAR}}}")

    resolve_env_placeholders([field])

    assert field.value == SECRET_VALUE
    assert field.env_var == SECRET_VAR


def test_resolve_env_placeholder_leaves_literals_untouched() -> None:
    """A non-placeholder value is left as-is with no backing variable."""
    field = ReflectedField(key="whatsapp.template_language", name="Lang", field_type=str, value=LITERAL_LANG)

    resolve_env_placeholders([field])

    assert field.value == LITERAL_LANG
    assert field.env_var is None


def test_deserialize_boolean_values() -> None:
    """It properly deserializes boolean inputs."""
    assert deserialize_value("true", bool) is True
    assert deserialize_value("yes", bool) is True
    assert deserialize_value("1", bool) is True
    assert deserialize_value("false", bool) is False
    assert deserialize_value(True, bool) is True


def test_deserialize_integer_values() -> None:
    """It deserializes valid integers and rejects invalid input."""
    assert deserialize_value("123", int) == 123
    with pytest.raises(ValueError):
        deserialize_value("not-an-int", int)


def test_deserialize_float_values() -> None:
    """It deserializes valid floats and rejects invalid input."""
    assert deserialize_value("12.34", float) == 12.34
    with pytest.raises(ValueError):
        deserialize_value("not-a-float", float)


def test_deserialize_choice_rejects_unknown() -> None:
    """It rejects a value outside the allowed choices instead of coercing."""
    with pytest.raises(ValueError):
        deserialize_value("maybe", Literal, choices=["yes", "no"])


def test_deserialize_list_values() -> None:
    """It properly deserializes list inputs."""
    assert deserialize_value("a, b, c", list[str]) == ["a", "b", "c"]
    assert deserialize_value("voxcpm,kokoro", list) == ["voxcpm", "kokoro"]
