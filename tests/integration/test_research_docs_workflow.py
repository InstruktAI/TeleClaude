"""Integration test for research_docs.py workflow."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

from teleclaude.constants import MAIN_MODULE

# Add root to sys.path
sys.path.append(os.getcwd())


class TestResearchDocsWorkflow(unittest.TestCase):
    """Integration test exercising the full research docs workflow."""

    def setUp(self):
        """Set up test directory and ensure it's clean."""
        self.test_dir = Path("docs/third-party")
        self.test_file = self.test_dir / "_test-doc.md"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        if self.test_file.exists():
            self.test_file.unlink()

    def tearDown(self):
        """Clean up test file only."""
        if self.test_file.exists():
            self.test_file.unlink()

    def test_end_to_end_workflow(self):
        """Test the full workflow of creating a doc and updating the index."""
        # Prepare test content
        title = "Test Library API"
        filename = "_test-doc.md"
        source = "https://example.com/docs"
        purpose = "Reference for testing the research workflow"
        content = """## Overview

This is a test document.

## Key Features

- Feature 1
- Feature 2

## Configuration

```yaml
key: value
```
"""

        # Run the script with all parameters, using test directory
        result = subprocess.run(
            [
                sys.executable,
                "scripts/research_docs.py",
                "--title",
                title,
                "--filename",
                filename,
                "--source",
                source,
                "--purpose",
                purpose,
                "--content",
                content,
                "--output-dir",
                str(self.test_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        # Verify script executed successfully
        self.assertEqual(
            result.returncode,
            0,
            f"Script failed with error:\nstdout: {result.stdout}\nstderr: {result.stderr}",
        )

        # Verify doc file was created in test directory
        doc_file = self.test_dir / filename
        self.assertTrue(doc_file.exists(), f"Doc file not created at {doc_file}")

        # Read and verify doc content
        doc_content = doc_file.read_text(encoding="utf-8")
        self.assertIn(title, doc_content)
        self.assertIn(source, doc_content)
        self.assertIn("## Overview", doc_content)
        self.assertIn("Feature 1", doc_content)

        # Index.md is no longer managed by research_docs.py (disallowed outside baseline)


if __name__ == MAIN_MODULE:
    unittest.main()
