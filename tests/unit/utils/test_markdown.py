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


# ---------------------------------------------------------------------------
# GFM tokenizer: N-backtick inline code and line-start fences
# ---------------------------------------------------------------------------


def test_gfm_double_backtick_inline_code_contains_literal_triple_backticks() -> None:
    """N-backtick inline code is atomic: content between matching runs is literal."""
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    # `` ``` `` — double-backtick inline code wrapping a literal triple backtick.
    # The inner ``` must NOT be interpreted as a code fence opener.
    text = "Approve to commit with `` ``` `` at the end"
    state = markdown.scan_gfm_state(text)

    assert state.stack == ()
    assert state.open_inline_code_run == 0
    assert markdown.continuation_prefix_for_gfm_state(state) == ""


def test_gfm_code_fence_mid_line_is_inline_not_fence() -> None:
    """A triple-backtick run that is not at the start of a line is inline code."""
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    text = "Run ```python code``` to test"
    state = markdown.scan_gfm_state(text)

    # Atomic 3-backtick inline span — no open state.
    assert state.stack == ()
    assert state.open_inline_code_run == 0


def test_gfm_code_fence_at_line_start_opens_fence() -> None:
    """A triple-backtick run at the start of a line opens a code fence."""
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    text = "Hello:\n```python\nprint(1)\n```\nDone"
    state = markdown.scan_gfm_state(text)

    # Balanced fence — closed by the time we reach "Done".
    assert state.stack == ()
    assert state.open_inline_code_run == 0


def test_gfm_unclosed_code_fence_carries_across_chunks() -> None:
    """A mid-chunk cut inside an open fence reports fence state for reopening."""
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    text = "Hi:\n```py\nprint(1)"  # no closing fence
    state = markdown.scan_gfm_state(text)

    assert state.stack == ("gfm_code_fence",)
    assert state.open_inline_code_run == 0
    assert markdown.continuation_prefix_for_gfm_state(state) == "```\n"


def test_gfm_unclosed_inline_code_carries_run_length() -> None:
    """A mid-chunk cut inside an open N-backtick span carries the run length."""
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    text = "Start ``some code"  # opens 2-backtick run, no closer
    state = markdown.scan_gfm_state(text)

    assert state.stack == ()
    assert state.open_inline_code_run == 2
    assert markdown.continuation_prefix_for_gfm_state(state) == "``"


def test_gfm_resume_scan_closes_open_inline_code_span() -> None:
    """Scanning with an open-inline-code initial state closes at matching run."""
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    initial = markdown.GfmMarkdownState(open_inline_code_run=2)
    # The next chunk starts inside a 2-backtick span. The closer `` appears,
    # then plain text — state should return to clean.
    state = markdown.scan_gfm_state("more code`` after", initial_state=initial)

    assert state.stack == ()
    assert state.open_inline_code_run == 0


def test_gfm_single_backtick_inline_code_is_atomic() -> None:
    """Single-backtick inline code spans are atomic."""
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    state = markdown.scan_gfm_state("Look at `foo` here")
    assert state.stack == ()
    assert state.open_inline_code_run == 0


def test_gfm_bold_and_strikethrough_toggle_across_cut() -> None:
    """Toggle-style markers still carry across chunk boundaries."""
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    state = markdown.scan_gfm_state("**bold open")
    assert state.stack == ("gfm_bold",)
    assert markdown.continuation_prefix_for_gfm_state(state) == "**"


def test_gfm_truncate_closes_open_inline_code_run_at_budget() -> None:
    """Truncating mid-span emits the matching closer to balance the chunk."""
    markdown = _import_markdown_module(lambda text, **_kwargs: text)

    text = "Prefix ``open run here that is long``"
    truncated, consumed = markdown.truncate_gfm_with_consumed(text, max_chars=15, suffix="")

    # The trimmer must produce balanced markdown (no dangling backtick runs).
    balanced_state = markdown.scan_gfm_state(truncated)
    assert balanced_state.stack == ()
    assert balanced_state.open_inline_code_run == 0
    assert 0 <= consumed <= len(text)
