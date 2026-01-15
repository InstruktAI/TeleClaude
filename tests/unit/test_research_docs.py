import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add root to sys.path
sys.path.append(os.getcwd())
from scripts.research_docs import update_index


class TestResearchDocs(unittest.TestCase):
    @patch("scripts.research_docs.os.path.exists")
    @patch("builtins.open")
    def test_update_index_new(self, mock_open, mock_exists):
        mock_exists.return_value = False

        # We need to capture what's written
        written_data = []

        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.writelines.side_effect = lambda x: written_data.extend(x)
        mock_open.return_value = mock_file

        update_index("Test Title", "test.md", "http://example.com", "Test purpose")

        self.assertIn("# Third‑Party Documentation Index\n", written_data)
        self.assertIn("## Test Title\n", written_data)
        self.assertIn("- File: `test.md`\n", written_data)
        self.assertIn("- Purpose: Test purpose\n", written_data)

    @patch("scripts.research_docs.os.path.exists")
    @patch("builtins.open")
    def test_update_index_existing(self, mock_open, mock_exists):
        mock_exists.return_value = True

        existing_content = [
            "# Third‑Party Documentation Index\n",
            "\n",
            "## Existing\n",
            "- Purpose: Old purpose\n",
            "- File: `existing.md`\n",
            "- Source: src\n",
            "- Last Updated: 2026-01-01\n",
        ]

        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.readlines.return_value = existing_content

        written_data = []
        mock_file.writelines.side_effect = lambda x: written_data.extend(x)
        mock_open.return_value = mock_file

        update_index("Existing", "existing.md", "new_src", "New purpose")

        # Check that it updated the existing entry
        self.assertIn("## Existing\n", written_data)
        self.assertIn("- Source: new_src\n", written_data)
        self.assertIn("- Purpose: New purpose\n", written_data)
        # Ensure it didn't just append
        self.assertEqual(written_data.count("## Existing\n"), 1)


if __name__ == "__main__":
    unittest.main()
