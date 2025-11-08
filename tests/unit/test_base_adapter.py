"""Unit tests for base_adapter.py."""

from teleclaude.adapters.base_adapter import AdapterError


class TestAdapterError:
    """Tests for AdapterError class."""

    def test_adapter_error_creation(self):
        """Test creating adapter error."""
        error = AdapterError("Test error")
        assert str(error) == "Test error"

    def test_adapter_error_raise(self):
        """Test raising adapter error."""
        try:
            raise AdapterError("Test error")
        except AdapterError as e:
            assert str(e) == "Test error"
