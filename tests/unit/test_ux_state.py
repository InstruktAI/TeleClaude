"""Unit tests for UX state management."""

import pytest


@pytest.mark.skip(reason="TODO: Implement test")
async def test_get_session_ux_state_loads_from_db():
    """Test that get_session_ux_state loads state from database.

    TODO: Test loading:
    - Mock DB with stored ux_state JSON
    - Verify SessionUXState returned
    - Verify fields parsed correctly
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_get_session_ux_state_returns_defaults_when_missing():
    """Test that get_session_ux_state returns defaults when no state stored.

    TODO: Test defaults:
    - Mock DB with no ux_state
    - Verify default SessionUXState returned
    - Verify all fields are defaults
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_get_session_ux_state_handles_invalid_json():
    """Test that get_session_ux_state handles corrupted JSON gracefully.

    TODO: Test error handling:
    - Mock DB with invalid JSON
    - Verify default SessionUXState returned
    - Verify warning logged
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_update_session_ux_state_merges_with_existing():
    """Test that update_session_ux_state merges partial updates.

    TODO: Test merging:
    - Mock existing state with some fields set
    - Update only one field
    - Verify other fields preserved
    - Verify updated field changed
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_update_session_ux_state_respects_sentinel_value():
    """Test that update_session_ux_state only updates provided fields.

    TODO: Test sentinel handling:
    - Mock existing state
    - Call update with some params as _UNSET
    - Verify only non-UNSET params updated
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_update_session_ux_state_allows_none_values():
    """Test that update_session_ux_state can set fields to None.

    TODO: Test None assignment:
    - Mock existing state with field set
    - Update field to None (not _UNSET)
    - Verify field is None
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_get_system_ux_state_loads_from_system_settings():
    """Test that get_system_ux_state loads from system_settings table.

    TODO: Test loading:
    - Mock system_settings table with ux_state
    - Verify SystemUXState returned
    - Verify registry fields parsed
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_update_system_ux_state_merges_registry_fields():
    """Test that update_system_ux_state merges registry fields.

    TODO: Test merging:
    - Mock existing registry state
    - Update only topic_id
    - Verify ping_message_id and pong_message_id preserved
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_session_ux_state_from_dict_handles_missing_fields():
    """Test that SessionUXState.from_dict handles missing fields gracefully.

    TODO: Test partial dict:
    - Create dict with only some fields
    - Verify from_dict uses defaults for missing
    """


@pytest.mark.skip(reason="TODO: Implement test")
async def test_session_ux_state_to_dict_serializes_all_fields():
    """Test that SessionUXState.to_dict includes all fields.

    TODO: Test serialization:
    - Create SessionUXState with various values
    - Call to_dict()
    - Verify all fields present in dict
    """
