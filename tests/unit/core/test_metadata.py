"""Characterization tests for teleclaude.core.metadata."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from teleclaude.core.metadata import AdapterMetadata


class TestAdapterMetadata:
    # AdapterMetadata is a Pydantic model; tests below cover both validation
    # behavior (required fields, extra fields) and field storage contracts.
    @pytest.mark.unit
    def test_requires_origin_field(self):
        with pytest.raises(ValidationError):
            AdapterMetadata()  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_valid_metadata_created_with_origin(self):
        m = AdapterMetadata(origin="telegram")  # type: ignore[call-arg]
        assert m.origin == "telegram"

    @pytest.mark.unit
    def test_optional_fields_default_to_none(self):
        m = AdapterMetadata(origin="api")  # type: ignore[call-arg]
        assert m.user_id is None
        assert m.message_id is None
        assert m.last_input_origin is None
        assert m.target_computer is None
        assert m.telegram is None
        assert m.redis is None

    @pytest.mark.unit
    def test_allows_extra_fields(self):
        m = AdapterMetadata(origin="discord", extra_custom_field="value")  # type: ignore[call-arg]
        assert m.origin == "discord"

    @pytest.mark.unit
    def test_user_id_can_be_set(self):
        m = AdapterMetadata(origin="telegram", user_id="12345")  # type: ignore[call-arg]
        assert m.user_id == "12345"

    @pytest.mark.unit
    def test_telegram_dict_can_be_set(self):
        m = AdapterMetadata(origin="telegram", telegram={"chat_id": 42})  # type: ignore[call-arg]
        assert m.telegram == {"chat_id": 42}
