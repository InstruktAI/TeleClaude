"""Characterization tests for teleclaude.utils.markdown."""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock, patch


def _import_markdown_module(markdownify_impl):
    instrukt_logging = types.ModuleType("instrukt_ai_logging")
    instrukt_logging.get_logger = lambda _name: MagicMock()
    telegramify = types.ModuleType("telegramify_markdown")
    telegramify.markdownify = markdownify_impl

    sys.modules.pop("teleclaude.utils.markdown", None)
    sys.modules.pop("teleclaude.utils", None)
    with patch.dict(
        sys.modules,
        {
            "instrukt_ai_logging": instrukt_logging,
            "telegramify_markdown": telegramify,
        },
    ):
        return importlib.import_module("teleclaude.utils.markdown")


def test_strip_outer_codeblock_removes_only_the_outer_fence() -> None:
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    assert markdown.strip_outer_codeblock("```python\nprint('hi')\n```") == "print('hi')"
    assert markdown.strip_outer_codeblock("plain text") == "plain text"


def test_escape_markdown_v2_escapes_special_chars_outside_code_regions() -> None:
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    escaped = markdown.escape_markdown_v2("a_b `c_d` ```\nx_y\n```")

    assert escaped == "a\\_b `c_d` ```\nx_y\n```"
    assert markdown.unescape_markdown_v2(escaped) == "a_b `c_d` ```\nx_y\n```"


def test_telegramify_markdown_strips_heading_icons_and_tags_plain_fences() -> None:
    markdown = _import_markdown_module(lambda text, **_kwargs: "*📌 Title*\n```\ncode\n```")

    assert markdown.telegramify_markdown("ignored") == "*Title*\n```md\ncode\n```"


def test_collapse_fenced_code_blocks_wraps_block_in_spoiler_payload() -> None:
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    collapsed = markdown.collapse_fenced_code_blocks("before\n```\ncode\n```\nafter")

    assert collapsed == "before\n📦 *CODE BLOCK*\n\n||```\ncode\n```||\nafter"


def test_scan_state_and_continuation_prefix_preserve_open_entities() -> None:
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    state = markdown.scan_markdown_v2_state("*bold [link](")

    assert state == markdown.MarkdownV2State(stack=("bold",), in_link_text=False, link_url_depth=1)
    assert markdown.continuation_prefix_for_markdown_v2_state(markdown.scan_markdown_v2_state("*bold ")) == "*"


def test_truncate_markdown_v2_balances_open_markers_and_reports_consumed_chars() -> None:
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    truncated, consumed = markdown.truncate_markdown_v2_with_consumed("*bold text* tail", max_chars=10, suffix="...")

    assert truncated == "*bold *..."
    assert consumed == 6
    assert markdown.truncate_markdown_v2("*bold text* tail", max_chars=10, suffix="...") == "*bold *..."


def test_truncate_markdown_v2_by_bytes_uses_suffix_when_budget_is_tiny() -> None:
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    assert markdown.truncate_markdown_v2_by_bytes("éééé", max_bytes=5, suffix="...") == "..."


def test_leading_balanced_markdown_v2_entity_span_covers_complete_leading_entity_only() -> None:
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    assert markdown.leading_balanced_markdown_v2_entity_span("*bold* tail") == 6
    assert markdown.leading_balanced_markdown_v2_entity_span("[link](https://x) tail") == 17
    assert markdown.leading_balanced_markdown_v2_entity_span("plain text") == 0
