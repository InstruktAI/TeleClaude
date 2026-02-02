"""Unit tests for research_docs script."""

from scripts.research_docs import update_index


def test_update_index_is_noop() -> None:
    """update_index is a no-op since index files are only in baseline."""
    # Should not raise
    result = update_index("Title", "file.md", "http://example.com", "Purpose")
    assert result is None
