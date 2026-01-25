"""Unit tests for config.py - TrustedDir parsing and ComputerConfig methods."""

from teleclaude.config import ComputerConfig, TrustedDir, _parse_trusted_dirs


class TestParseTrustedDirs:
    """Tests for _parse_trusted_dirs."""

    def test_parse_old_format_strings_rejected(self):
        """Old string-only format is rejected."""
        raw_dirs = ["/home/user/projects", "/tmp/workspace", "/var/data"]

        try:
            _parse_trusted_dirs(raw_dirs)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Invalid trusted_dirs entry type" in str(e)

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

    def test_parse_mixed_format_rejected(self):
        """Mixed formats are rejected."""
        raw_dirs = [
            "/home/user/old",
            {"name": "new", "desc": "new format", "path": "/home/user/new"},
        ]

        try:
            _parse_trusted_dirs(raw_dirs)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Invalid trusted_dirs entry type" in str(e)

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
