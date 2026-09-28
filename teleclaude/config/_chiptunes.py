"""Chiptunes configuration parsing."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import model_validator

from teleclaude.closed_model import ClosedModel
from teleclaude.config._coerce import FLAG, TRUTHY_TEXT

_CHIPTUNES_MAPPING_ERROR = "Invalid config key `config.yml:chiptunes`: expected a mapping."
_CHIPTUNES_VOLUME_KEY = "volume"


class ChiptunesConfig(ClosedModel):
    enabled: FLAG = False
    music_dir: TRUTHY_TEXT = None
    volume: float = 1.0

    @model_validator(mode="before")
    @classmethod
    def _default_null_chiptunes_section(cls, value: object) -> object:
        if value is None:
            return {_CHIPTUNES_VOLUME_KEY: 0.5}
        if not isinstance(value, Mapping):
            raise ValueError(_CHIPTUNES_MAPPING_ERROR)
        return value
