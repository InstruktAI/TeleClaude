"""Tests for content scaffolding."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict
from unittest.mock import MagicMock, patch

import pytest
import yaml

from teleclaude.content_scaffold import _derive_slug, create_content_inbox_entry


class _CliCallArgs(TypedDict):
    text: str
    slug: str | None
    tags: list[str] | None
    author: str | None


class TestDeriveSlug:
    def test_basic_phrase(self) -> None:
        assert _derive_slug("The moment we realized") == "the-moment-we-realized"

    def test_strips_punctuation(self) -> None:
        assert _derive_slug("Hello, world! This is a test.") == "hello-world-this-is-test"

    def test_takes_up_to_five_words(self) -> None:
        result = _derive_slug("one two three four five six seven")
        assert result == "one-two-three-four-five"

    def test_empty_text_falls_back(self) -> None:
        assert _derive_slug("") == "dump"

    def test_only_punctuation_falls_back(self) -> None:
        assert _derive_slug("!!!") == "dump"

    def test_single_char_words_excluded(self) -> None:
        result = _derive_slug("a b c deep dive into mesh")
        assert "deep" in result


class TestCreateContentInboxEntry:
    def test_creates_folder_structure(self, tmp_path: Path) -> None:
        with patch("teleclaude.content_scaffold._emit_content_dumped"):
            entry = create_content_inbox_entry(tmp_path, "Hello world content")

        assert entry.exists()
        assert (entry / "content.md").exists()
        assert (entry / "meta.yaml").exists()

    def test_content_md_contains_text(self, tmp_path: Path) -> None:
        text = "My brain dump about agent shorthand"
        with patch("teleclaude.content_scaffold._emit_content_dumped"):
            entry = create_content_inbox_entry(tmp_path, text)

        assert (entry / "content.md").read_text() == text

    def test_meta_yaml_fields(self, tmp_path: Path) -> None:
        with patch("teleclaude.content_scaffold._emit_content_dumped"):
            with patch("teleclaude.content_scaffold._resolve_author", return_value="test-author"):
                entry = create_content_inbox_entry(
                    tmp_path,
                    "Some content",
                    tags=["tag1", "tag2"],
                )

        meta = yaml.safe_load((entry / "meta.yaml").read_text())
        assert meta["author"] == "test-author"
        assert meta["tags"] == ["tag1", "tag2"]
        assert "created_at" in meta

    def test_custom_slug_used(self, tmp_path: Path) -> None:
        with patch("teleclaude.content_scaffold._emit_content_dumped"):
            entry = create_content_inbox_entry(tmp_path, "Some content", slug="my-custom-slug")

        assert entry.name.endswith("-my-custom-slug")

    def test_auto_slug_from_text(self, tmp_path: Path) -> None:
        with patch("teleclaude.content_scaffold._emit_content_dumped"):
            entry = create_content_inbox_entry(tmp_path, "Deep dive into mesh architecture")

        assert "deep" in entry.name or "dive" in entry.name

    def test_dated_prefix(self, tmp_path: Path) -> None:
        from datetime import UTC, datetime

        today = datetime.now(UTC).strftime("%Y%m%d")
        with patch("teleclaude.content_scaffold._emit_content_dumped"):
            entry = create_content_inbox_entry(tmp_path, "Some content")

        assert entry.name.startswith(today)

    def test_collision_appends_counter(self, tmp_path: Path) -> None:
        with patch("teleclaude.content_scaffold._emit_content_dumped"):
            entry1 = create_content_inbox_entry(tmp_path, "Same content", slug="same-slug")
            entry2 = create_content_inbox_entry(tmp_path, "Same content", slug="same-slug")

        assert entry1 != entry2
        assert entry2.name.endswith("-2")

    def test_collision_counter_increments(self, tmp_path: Path) -> None:
        with patch("teleclaude.content_scaffold._emit_content_dumped"):
            create_content_inbox_entry(tmp_path, "X", slug="slug-x")
            create_content_inbox_entry(tmp_path, "X", slug="slug-x")
            entry3 = create_content_inbox_entry(tmp_path, "X", slug="slug-x")

        assert entry3.name.endswith("-3")

    def test_author_override(self, tmp_path: Path) -> None:
        with patch("teleclaude.content_scaffold._emit_content_dumped"):
            entry = create_content_inbox_entry(tmp_path, "Content", author="override-author")

        meta = yaml.safe_load((entry / "meta.yaml").read_text())
        assert meta["author"] == "override-author"

    def test_unknown_author_fallback(self, tmp_path: Path) -> None:
        with patch("teleclaude.content_scaffold._emit_content_dumped"):
            with patch("teleclaude.content_scaffold._resolve_author", return_value="unknown"):
                entry = create_content_inbox_entry(tmp_path, "Content")

        meta = yaml.safe_load((entry / "meta.yaml").read_text())
        assert meta["author"] == "unknown"

    def test_empty_tags_default(self, tmp_path: Path) -> None:
        with patch("teleclaude.content_scaffold._emit_content_dumped"):
            entry = create_content_inbox_entry(tmp_path, "Content")

        meta = yaml.safe_load((entry / "meta.yaml").read_text())
        assert meta["tags"] == []

    def test_notification_called_with_correct_args(self, tmp_path: Path) -> None:
        mock_emit = MagicMock()
        with patch("teleclaude.content_scaffold._emit_content_dumped", mock_emit):
            with patch("teleclaude.content_scaffold._resolve_author", return_value="test-user"):
                create_content_inbox_entry(tmp_path, "Content", slug="notify-slug", tags=["a", "b"])

        mock_emit.assert_called_once()
        _, kwargs = mock_emit.call_args
        assert kwargs["author"] == "test-user"
        assert kwargs["tags"] == ["a", "b"]
        assert "notify-slug" in kwargs["inbox_path"]


class TestContentDumpCliArgs:
    """Test CLI-level arg parsing for telec content dump."""

    def _run(
        self,
        args: list[str],
        tmp_path: Path,
    ) -> _CliCallArgs:
        """Run _handle_content_dump with mocked scaffold, return captured call args."""
        captured: _CliCallArgs = {"text": "", "slug": None, "tags": None, "author": None}

        def fake_create(
            _root: Path,
            text: str,
            *,
            slug: str | None = None,
            tags: list[str] | None = None,
            author: str | None = None,
        ) -> Path:
            captured.update({"text": text, "slug": slug, "tags": tags, "author": author})
            fake_dir = tmp_path / "publications" / "inbox" / "fake"
            fake_dir.mkdir(parents=True, exist_ok=True)
            return fake_dir

        with patch("teleclaude.content_scaffold.create_content_inbox_entry", fake_create):
            with patch("teleclaude.content_scaffold._emit_content_dumped"):
                with patch.object(Path, "cwd", return_value=tmp_path):
                    import teleclaude.cli.telec as m

                    m._handle_content_dump(args)

        return captured

    def test_basic_text(self, tmp_path: Path) -> None:
        got = self._run(["My brain dump text"], tmp_path)
        assert got["text"] == "My brain dump text"
        assert got["slug"] is None
        assert got["tags"] is None
        assert got["author"] is None

    def test_all_flags(self, tmp_path: Path) -> None:
        got = self._run(
            ["Some text", "--slug", "my-slug", "--tags", "a,b,c", "--author", "alice"],
            tmp_path,
        )
        assert got["text"] == "Some text"
        assert got["slug"] == "my-slug"
        assert got["tags"] == ["a", "b", "c"]
        assert got["author"] == "alice"

    def test_missing_text_exits(self, tmp_path: Path) -> None:
        """Flags-only invocation (no positional text) should exit with error."""
        with pytest.raises(SystemExit):
            self._run(["--tags", "foo"], tmp_path)
