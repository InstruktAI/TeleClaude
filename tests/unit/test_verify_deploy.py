"""Tests for tools/verify_deploy.py."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the module under test by path since it is in tools/
# We need to add tools/ to sys.path
TOOLS_DIR = Path(__file__).parents[2] / "tools"
sys.path.append(str(TOOLS_DIR))

import verify_deploy  # type: ignore


@pytest.fixture
def mock_print():
    with patch("builtins.print") as mock:
        yield mock


@pytest.fixture
def mock_shutil_which():
    with patch("shutil.which") as mock:
        yield mock


@pytest.fixture
def mock_path_exists():
    with patch("pathlib.Path.exists") as mock:
        yield mock


@pytest.fixture
def mock_path_read_text():
    with patch("pathlib.Path.read_text") as mock:
        yield mock


def test_check_binary_found(mock_shutil_which, mock_print):
    """Test check_binary when binary exists."""
    mock_shutil_which.return_value = "/usr/bin/test-bin"
    assert verify_deploy.check_binary("test-bin") is True
    mock_print.assert_called_with(f"{verify_deploy.GREEN}✓{verify_deploy.NC} Found test-bin at /usr/bin/test-bin")


def test_check_binary_missing_required(mock_shutil_which, mock_print):
    """Test check_binary when required binary is missing."""
    mock_shutil_which.return_value = None
    assert verify_deploy.check_binary("test-bin") is False
    mock_print.assert_called_with(f"{verify_deploy.RED}✗{verify_deploy.NC} Missing required binary: test-bin")


def test_check_binary_missing_optional(mock_shutil_which, mock_print):
    """Test check_binary when optional binary is missing."""
    mock_shutil_which.return_value = None
    assert verify_deploy.check_binary("test-bin", required=False) is False
    mock_print.assert_called_with(f"{verify_deploy.YELLOW}⚠{verify_deploy.NC} Missing optional binary: test-bin")


def test_check_file_found(mock_path_exists, mock_print):
    """Test check_file when file exists."""
    mock_path_exists.return_value = True
    path = Path("/tmp/test.file")
    assert verify_deploy.check_file(path, "Test File") is True
    mock_print.assert_called_with(f"{verify_deploy.GREEN}✓{verify_deploy.NC} Found Test File: {path}")


def test_check_file_missing(mock_path_exists, mock_print):
    """Test check_file when file is missing."""
    mock_path_exists.return_value = False
    path = Path("/tmp/test.file")
    assert verify_deploy.check_file(path, "Test File") is False
    mock_print.assert_called_with(f"{verify_deploy.RED}✗{verify_deploy.NC} Missing Test File: {path}")


def test_check_json_config_valid(mock_path_exists, mock_path_read_text, mock_print):
    """Test check_json_config with valid JSON and all keys."""
    mock_path_exists.return_value = True
    mock_path_read_text.return_value = '{"key1": "val1", "key2": "val2"}'

    path = Path("/tmp/config.json")
    assert verify_deploy.check_json_config(path, ["key1", "key2"]) is True

    # Verify success log
    mock_print.assert_any_call(f"{verify_deploy.GREEN}✓{verify_deploy.NC} Valid JSON in {path}")


def test_check_json_config_missing_keys(mock_path_exists, mock_path_read_text, mock_print):
    """Test check_json_config with valid JSON but missing keys."""
    mock_path_exists.return_value = True
    mock_path_read_text.return_value = '{"key1": "val1"}'

    path = Path("/tmp/config.json")
    assert verify_deploy.check_json_config(path, ["key1", "key2"]) is False

    # Verify warning log
    mock_print.assert_called_with(f"{verify_deploy.YELLOW}⚠{verify_deploy.NC} Config {path} missing keys/values: key2")


def test_check_json_config_invalid_json(mock_path_exists, mock_path_read_text, mock_print):
    """Test check_json_config with invalid JSON."""
    mock_path_exists.return_value = True
    mock_path_read_text.return_value = "{invalid-json"

    path = Path("/tmp/config.json")
    assert verify_deploy.check_json_config(path) is False

    # Verify error log
    mock_print.assert_called_with(f"{verify_deploy.RED}✗{verify_deploy.NC} Invalid JSON in {path}")


def test_integration_run(mock_shutil_which, mock_path_exists, mock_path_read_text):
    """Smoke test for main execution logic."""
    # Mock system binaries
    mock_shutil_which.side_effect = lambda x: f"/usr/bin/{x}"

    # Mock file existence
    mock_path_exists.return_value = True

    # Mock config content
    mock_path_read_text.return_value = json.dumps({"teleclaude": {}, "context7": {}, "mcp-wrapper.py": ""})

    # Just ensure it runs without crashing
    with patch("pathlib.Path.home") as mock_home:
        mock_home.return_value = Path("/tmp")
        verify_deploy.main()
