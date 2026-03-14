"""Characterization tests for teleclaude.core.file_handler."""

from __future__ import annotations

import pytest

from teleclaude.core.file_handler import sanitize_filename


class TestSanitizeFilename:
    @pytest.mark.unit
    def test_plain_filename_unchanged(self):
        result = sanitize_filename("report.pdf")
        assert result == "report.pdf"

    @pytest.mark.unit
    def test_spaces_replaced_with_underscore(self):
        result = sanitize_filename("my file name.txt")
        assert " " not in result
        assert result.endswith(".txt")

    @pytest.mark.unit
    def test_path_traversal_dots_stripped(self):
        # Leading dots/underscores stripped by strip("._")
        result = sanitize_filename("../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    @pytest.mark.unit
    def test_special_chars_replaced(self):
        result = sanitize_filename("file@name!.csv")
        assert "@" not in result
        assert "!" not in result

    @pytest.mark.unit
    def test_empty_filename_returns_file(self):
        result = sanitize_filename("")
        assert result == "file"

    @pytest.mark.unit
    def test_only_special_chars_returns_file(self):
        result = sanitize_filename("@@@!!!")
        assert result == "file"

    @pytest.mark.unit
    def test_underscore_and_dash_preserved(self):
        result = sanitize_filename("my_file-name.log")
        assert result == "my_file-name.log"
