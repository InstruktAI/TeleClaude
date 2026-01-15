"""Integration test for research_docs.py workflow."""

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

# Add root to sys.path
sys.path.append(os.getcwd())


class TestResearchDocsWorkflow(unittest.TestCase):
    """Integration test exercising the full research docs workflow."""

    def setUp(self):
        """Set up test directory and ensure it's clean."""
        self.test_dir = Path("docs/3rd_test")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.test_dir / "index.md"
        self.doc_path = self.test_dir / "test-doc.md"

    def tearDown(self):
        """Clean up test directory."""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_end_to_end_workflow(self):
        """Test the full workflow of creating a doc and updating the index."""
        # Prepare test content
        title = "Test Library API"
        filename = "test-doc.md"
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

        # Run the script with all parameters
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

        # Verify doc file was created
        doc_file = Path("docs/3rd") / filename
        self.assertTrue(doc_file.exists(), f"Doc file not created at {doc_file}")

        # Read and verify doc content
        doc_content = doc_file.read_text(encoding="utf-8")
        self.assertIn(title, doc_content)
        self.assertIn(source, doc_content)
        self.assertIn("## Overview", doc_content)
        self.assertIn("Feature 1", doc_content)

        # Verify index was updated
        index_file = Path("docs/3rd/index.md")
        self.assertTrue(index_file.exists(), "Index file not created")

        # Read and verify index content
        index_content = index_file.read_text(encoding="utf-8")
        self.assertIn(f"## {title}", index_content)
        self.assertIn(f"- Purpose: {purpose}", index_content)
        self.assertIn(f"- File: `{filename}`", index_content)
        self.assertIn(f"- Source: {source}", index_content)
        self.assertIn("- Last Updated:", index_content)

        # Clean up the test doc and index entry
        doc_file.unlink()

        # Restore original index if it was backed up
        # For now, just leave the index with the test entry
        # In a real scenario, we'd want to restore the original state


if __name__ == "__main__":
    unittest.main()
