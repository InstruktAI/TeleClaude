import os
import shutil
import sys
import unittest
from datetime import datetime
from io import StringIO
from unittest.mock import patch

# Add root to sys.path
sys.path.append(os.getcwd())
from scripts.research_docs import main, update_index


class TestResearchDocs(unittest.TestCase):
    def setUp(self):
        self.test_dir = "docs/3rd_test"
        os.makedirs(self.test_dir, exist_ok=True)
        self.index_path = os.path.join(self.test_dir, "index.md")

        # Patch the paths in the script to use our test directory
        self.original_index_path = "docs/3rd/index.md"
        # We'll mock the open calls or just temporarily change the paths if possible
        # For simplicity in this test, we will just point to a different file if we can
        # but the script has hardcoded paths. Let's use patch.

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    @patch("scripts.research_docs.os.path.exists")
    @patch("builtins.open")
    def test_update_index_new(self, mock_open, mock_exists):
        mock_exists.return_value = False

        # We need to capture what's written
        written_data = []

        def mock_write(data):
            written_data.append(data)

        from unittest.mock import MagicMock

        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.writelines.side_effect = lambda x: written_data.extend(x)
        mock_open.return_value = mock_file

        update_index("Test Title", "test.md", "http://example.com")

        self.assertIn("# Third‑Party Documentation Index\n", written_data)
        self.assertIn("## Test Title\n", written_data)
        self.assertIn("- File: `test.md`\n", written_data)

    @patch("scripts.research_docs.os.path.exists")
    @patch("builtins.open")
    def test_update_index_existing(self, mock_open, mock_exists):
        mock_exists.return_value = True

        existing_content = [
            "# Third‑Party Documentation Index\n",
            "\n",
            "## Existing\n",
            "- File: `existing.md`\n",
            "- Source: src\n",
            "- Last Updated: 2026-01-01\n",
        ]

        from unittest.mock import MagicMock

        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.readlines.return_value = existing_content

        written_data = []
        mock_file.writelines.side_effect = lambda x: written_data.extend(x)
        mock_open.return_value = mock_file

        update_index("Existing", "existing.md", "new_src")

        # Check that it updated the existing entry
        self.assertIn("## Existing\n", written_data)
        self.assertIn("- Source: new_src\n", written_data)
        # Ensure it didn't just append
        self.assertEqual(written_data.count("## Existing\n"), 1)


if __name__ == "__main__":
    unittest.main()
