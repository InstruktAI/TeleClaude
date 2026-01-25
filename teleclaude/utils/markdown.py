"""Markdown formatting utilities for Telegram MarkdownV2."""

import re
from typing import Protocol

from telegramify_markdown import markdownify as _markdownify

from teleclaude.constants import MARKDOWN_FENCE, MARKDOWN_INLINE_CODE


class MarkdownifyFn(Protocol):
    def __call__(
        self,
        content: str,
        *,
        max_line_length: int = 0,
        normalize_whitespace: bool = False,
        latex_escape: bool = True,
    ) -> str: ...


markdownify: MarkdownifyFn = _markdownify


def strip_outer_codeblock(text: str) -> str:
    """Strip outer triple-backtick wrapper if present.

    AI agents often wrap output in code blocks. This removes the outer wrapper
    while preserving inner formatting (tables, code blocks, lists).

    Args:
        text: Input text that may have outer code block

    Returns:
        Text with outer code block removed, or original if no outer wrapper
    """
    # Match outer code block with optional language identifier
    pattern = re.compile(r"^```\w*\n(.*)\n```$", re.DOTALL)
    match = pattern.match(text.strip())

    if match:
        return match.group(1)

    return text


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2 format.

    Telegram's MarkdownV2 requires escaping these characters outside code blocks:
    _ * [ ] ( ) ~ ` > # + - = | { } . !

    This function escapes literal special characters while preserving intentional
    formatting (bold, italic, code blocks).

    Args:
        text: Input markdown text

    Returns:
        Text with MarkdownV2 special characters escaped
    """
    # Characters that need escaping in MarkdownV2 (outside code blocks)
    special_chars = r"_*[]()~`>#+-=|{}.!"

    # Track if we're inside a code block to avoid escaping there
    in_code_block = False
    in_inline_code = False
    result: list[str] = []
    i = 0

    while i < len(text):
        # Check for code block delimiters (```)
        if text[i : i + 3] == MARKDOWN_FENCE:
            in_code_block = not in_code_block
            result.append(MARKDOWN_FENCE)
            i += 3
            continue

        # Check for inline code delimiters (`)
        if text[i] == MARKDOWN_INLINE_CODE and not in_code_block:
            in_inline_code = not in_inline_code
            result.append(MARKDOWN_INLINE_CODE)
            i += 1
            continue

        # Escape special characters (unless inside code)
        if not in_code_block and not in_inline_code and text[i] in special_chars:
            result.append("\\" + text[i])
        else:
            result.append(text[i])

        i += 1

    return "".join(result)


def telegramify_markdown(text: str, *, strip_heading_icons: bool = True) -> str:
    """Convert GitHub-style markdown to Telegram MarkdownV2-friendly format.

    Applies telegramify_markdown, escapes nested backticks inside code blocks,
    and adds `md` language tag to plain code blocks for Telegram rendering.
    """
    formatted = markdownify(text)
    if strip_heading_icons:
        formatted = _strip_heading_icons(formatted)
    formatted = _escape_nested_backticks(formatted)
    formatted = re.sub(r"^```\n(?!\n|$)", "```md\n", formatted, flags=re.MULTILINE)
    return formatted


def _escape_nested_backticks(text: str) -> str:
    """Escape ``` inside code blocks to avoid breaking the outer fence."""

    def escape_nested_backticks(match: re.Match[str]) -> str:
        lang = str(match.group(1) or "")
        block_content = str(match.group(2))
        escaped = block_content.replace(
            MARKDOWN_FENCE, f"{MARKDOWN_INLINE_CODE}\u200b{MARKDOWN_INLINE_CODE}{MARKDOWN_INLINE_CODE}"
        )
        return f"{MARKDOWN_FENCE}{lang}\n{escaped}{MARKDOWN_FENCE}"

    return re.sub(r"```(\w*)\n(.*?)```", escape_nested_backticks, text, flags=re.DOTALL)


def _strip_heading_icons(text: str) -> str:
    """Remove emoji prefixes added by telegramify_markdown heading conversion."""
    heading_icons = ("\U0001f4cc", "\u270f", "\U0001f4da", "\U0001f516")
    icon_pattern = re.compile(rf"^\*(?:{'|'.join(map(re.escape, heading_icons))}) (.+)\*$")
    lines: list[str] = []
    in_code_block = False

    for line in text.splitlines():
        if line.startswith("```"):
            in_code_block = not in_code_block
            lines.append(line)
            continue

        if not in_code_block:
            match = icon_pattern.match(line)
            if match:
                lines.append(f"*{match.group(1)}*")
                continue

        lines.append(line)

    return "\n".join(lines)
