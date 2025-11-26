"""Unit tests for config.py - TrustedDir parsing and ComputerConfig methods."""

from teleclaude.config import ComputerConfig, TrustedDir, _parse_trusted_dirs


class TestParseTrustedDirs:
    """Tests for _parse_trusted_dirs backward compatibility."""

    def test_parse_old_format_strings(self):
        """Test parsing old format (list of strings) converts correctly."""
        raw_dirs = ["/home/user/projects", "/tmp/workspace", "/var/data"]

        result = _parse_trusted_dirs(raw_dirs)

        assert len(result) == 3
        assert all(isinstance(d, TrustedDir) for d in result)

        # Check first entry
        assert result[0].name == "projects"
        assert result[0].desc == ""
        assert result[0].path == "/home/user/projects"

        # Check second entry
        assert result[1].name == "workspace"
        assert result[1].desc == ""
        assert result[1].path == "/tmp/workspace"

        # Check third entry (trailing slash should be stripped for name)
        assert result[2].name == "data"
        assert result[2].desc == ""
        assert result[2].path == "/var/data"

    def test_parse_new_format_dicts(self):
        """Test parsing new format (list of dicts) works correctly."""
        raw_dirs = [
            {"name": "development", "desc": "dev projects", "path": "/home/user/dev"},
            {"name": "documents", "desc": "personal docs", "path": "/home/user/docs"},
        ]

        result = _parse_trusted_dirs(raw_dirs)

        assert len(result) == 2

        assert result[0].name == "development"
        assert result[0].desc == "dev projects"
        assert result[0].path == "/home/user/dev"

        assert result[1].name == "documents"
        assert result[1].desc == "personal docs"
        assert result[1].path == "/home/user/docs"

    def test_parse_new_format_with_missing_desc(self):
        """Test parsing new format with missing desc defaults to empty string."""
        raw_dirs = [
            {"name": "myproject", "path": "/home/user/project"},
        ]

        result = _parse_trusted_dirs(raw_dirs)

        assert len(result) == 1
        assert result[0].name == "myproject"
        assert result[0].desc == ""
        assert result[0].path == "/home/user/project"

    def test_parse_mixed_format(self):
        """Test parsing mixed old and new formats (edge case)."""
        raw_dirs = [
            "/home/user/old",
            {"name": "new", "desc": "new format", "path": "/home/user/new"},
        ]

        result = _parse_trusted_dirs(raw_dirs)

        assert len(result) == 2

        # Old format entry
        assert result[0].name == "old"
        assert result[0].desc == ""
        assert result[0].path == "/home/user/old"

        # New format entry
        assert result[1].name == "new"
        assert result[1].desc == "new format"
        assert result[1].path == "/home/user/new"

    def test_parse_empty_list(self):
        """Test parsing empty list returns empty list."""
        result = _parse_trusted_dirs([])
        assert result == []

    def test_parse_invalid_type_raises_error(self):
        """Test parsing invalid entry type raises ValueError."""
        raw_dirs = [123, 456]  # Invalid: numbers instead of strings or dicts

        try:
            _parse_trusted_dirs(raw_dirs)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Invalid trusted_dirs entry type" in str(e)


class TestGetAllTrustedDirs:
    """Tests for ComputerConfig.get_all_trusted_dirs() method."""

    def test_includes_default_working_dir_first(self):
        """Test that default_working_dir is always included first."""
        config = ComputerConfig(
            name="test",
            user="testuser",
            role="dev",
            timezone="UTC",
            default_shell="/bin/bash",
            default_working_dir="/home/teleclaude",
            is_master=False,
            trusted_dirs=[
                TrustedDir(name="projects", desc="my projects", path="/home/projects"),
            ],
            host=None,
        )

        result = config.get_all_trusted_dirs()

        assert len(result) == 2
        assert result[0].name == "teleclaude"
        assert result[0].desc == "TeleClaude folder"
        assert result[0].path == "/home/teleclaude"

    def test_deduplicates_by_path(self):
        """Test that duplicate paths are removed."""
        config = ComputerConfig(
            name="test",
            user="testuser",
            role="dev",
            timezone="UTC",
            default_shell="/bin/bash",
            default_working_dir="/home/teleclaude",
            is_master=False,
            trusted_dirs=[
                TrustedDir(name="teleclaude_dup", desc="duplicate", path="/home/teleclaude"),
                TrustedDir(name="projects", desc="my projects", path="/home/projects"),
            ],
            host=None,
        )

        result = config.get_all_trusted_dirs()

        # Should only have 2 items (default_working_dir + projects, duplicate removed)
        assert len(result) == 2
        assert result[0].path == "/home/teleclaude"
        assert result[1].path == "/home/projects"

    def test_empty_trusted_dirs(self):
        """Test with empty trusted_dirs list."""
        config = ComputerConfig(
            name="test",
            user="testuser",
            role="dev",
            timezone="UTC",
            default_shell="/bin/bash",
            default_working_dir="/home/teleclaude",
            is_master=False,
            trusted_dirs=[],
            host=None,
        )

        result = config.get_all_trusted_dirs()

        assert len(result) == 1
        assert result[0].name == "teleclaude"
        assert result[0].desc == "TeleClaude folder"
        assert result[0].path == "/home/teleclaude"

    def test_preserves_order(self):
        """Test that order is preserved (default_working_dir first, then trusted_dirs)."""
        config = ComputerConfig(
            name="test",
            user="testuser",
            role="dev",
            timezone="UTC",
            default_shell="/bin/bash",
            default_working_dir="/home/teleclaude",
            is_master=False,
            trusted_dirs=[
                TrustedDir(name="a", desc="first", path="/a"),
                TrustedDir(name="b", desc="second", path="/b"),
                TrustedDir(name="c", desc="third", path="/c"),
            ],
            host=None,
        )

        result = config.get_all_trusted_dirs()

        assert len(result) == 4
        assert result[0].path == "/home/teleclaude"
        assert result[1].path == "/a"
        assert result[2].path == "/b"
        assert result[3].path == "/c"
