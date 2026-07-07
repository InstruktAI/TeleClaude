"""Additive-field coverage for ``PersonConfig.preferred_channel``.

``preferred_channel`` is the recipient-owned default delivery channel for
person-addressed messaging (``project/spec/teleclaude-config``, per-person
keys). It is a purely additive optional field, so a pre-change person config
file (no ``preferred_channel`` key) must still load, defaulting to ``None`` —
the resolver, not the schema, applies the ``telegram`` fallback.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from ruamel.yaml import YAML

from teleclaude.config.loader import load_person_config
from teleclaude.config.schema import MessagingChannel, PersonConfig

pytestmark = pytest.mark.functional


def test_pre_change_person_config_loads_with_no_preferred_channel(tmp_path) -> None:
    yaml = YAML(typ="safe")
    config_path = tmp_path / "teleclaude.yml"
    with config_path.open("w", encoding="utf-8") as f:
        yaml.dump({"creds": {"telegram": {"user_name": "alex", "user_id": 111}}}, f)

    person_config = load_person_config(config_path)

    assert person_config.preferred_channel is None


def test_preferred_channel_round_trips_through_config_file(tmp_path) -> None:
    yaml = YAML(typ="safe")
    config_path = tmp_path / "teleclaude.yml"
    with config_path.open("w", encoding="utf-8") as f:
        yaml.dump({"preferred_channel": "discord"}, f)

    person_config = load_person_config(config_path)

    assert person_config.preferred_channel is MessagingChannel.DISCORD


def test_preferred_channel_rejects_value_outside_the_channel_vocabulary() -> None:
    with pytest.raises(ValidationError):
        PersonConfig(preferred_channel="sms")
