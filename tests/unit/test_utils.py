"""Unit tests for utils module."""

import os

from teleclaude.utils import expand_env_vars


class TestExpandEnvVars:
    """Tests for expand_env_vars() function."""

    def test_expand_simple_env_var(self):
        """Test expanding a simple environment variable."""
        os.environ["TEST_VAR"] = "test_value"

        result = expand_env_vars("Hello ${TEST_VAR}!")

        assert result == "Hello test_value!"

        # Cleanup
        del os.environ["TEST_VAR"]

    def test_expand_multiple_env_vars(self):
        """Test expanding multiple environment variables in same string."""
        os.environ["VAR1"] = "value1"
        os.environ["VAR2"] = "value2"

        result = expand_env_vars("${VAR1} and ${VAR2}")

        assert result == "value1 and value2"

        # Cleanup
        del os.environ["VAR1"]
        del os.environ["VAR2"]

    def test_expand_nonexistent_env_var(self):
        """Test that nonexistent env var is kept as-is."""
        result = expand_env_vars("Hello ${NONEXISTENT_VAR}!")

        assert result == "Hello ${NONEXISTENT_VAR}!"

    def test_expand_dict_config(self):
        """Test expanding env vars in dict config."""
        os.environ["TEST_HOME"] = "/home/test"

        config = {"path": "${TEST_HOME}/project", "name": "test"}

        result = expand_env_vars(config)

        assert result["path"] == "/home/test/project"
        assert result["name"] == "test"

        # Cleanup
        del os.environ["TEST_HOME"]

    def test_expand_nested_dict_config(self):
        """Test expanding env vars in nested dict config."""
        os.environ["TEST_VAR"] = "nested_value"

        config = {"outer": {"inner": {"value": "${TEST_VAR}"}}}

        result = expand_env_vars(config)

        assert result["outer"]["inner"]["value"] == "nested_value"

        # Cleanup
        del os.environ["TEST_VAR"]

    def test_expand_list_config(self):
        """Test expanding env vars in list config."""
        os.environ["DIR1"] = "/path/one"
        os.environ["DIR2"] = "/path/two"

        config = ["${DIR1}", "${DIR2}", "static_value"]

        result = expand_env_vars(config)

        assert result == ["/path/one", "/path/two", "static_value"]

        # Cleanup
        del os.environ["DIR1"]
        del os.environ["DIR2"]

    def test_expand_mixed_config(self):
        """Test expanding env vars in complex mixed config."""
        os.environ["TEST_PATH"] = "/test/path"

        config = {"paths": ["${TEST_PATH}/one", "${TEST_PATH}/two"], "settings": {"base": "${TEST_PATH}"}}

        result = expand_env_vars(config)

        assert result["paths"] == ["/test/path/one", "/test/path/two"]
        assert result["settings"]["base"] == "/test/path"

        # Cleanup
        del os.environ["TEST_PATH"]

    def test_expand_primitive_types(self):
        """Test that primitive types are returned as-is."""
        assert expand_env_vars(42) == 42
        assert expand_env_vars(True) is True
        assert expand_env_vars(None) is None
        assert expand_env_vars(3.14) == 3.14

    def test_expand_string_without_vars(self):
        """Test string without env vars is returned as-is."""
        result = expand_env_vars("Just a plain string")

        assert result == "Just a plain string"

    def test_expand_empty_string(self):
        """Test empty string is returned as-is."""
        result = expand_env_vars("")

        assert result == ""

    def test_expand_empty_dict(self):
        """Test empty dict is returned as-is."""
        result = expand_env_vars({})

        assert result == {}

    def test_expand_empty_list(self):
        """Test empty list is returned as-is."""
        result = expand_env_vars([])

        assert result == []
