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


def unescape_markdown_v2(text: str) -> str:
    """Remove MarkdownV2 escape prefixes for plain-text fallback rendering."""
    return re.sub(r"\\([_*\[\]()~`>#+\-=|{}.!])", r"\1", text)


def telegramify_markdown(
    text: str,
    *,
    strip_heading_icons: bool = True,
    collapse_code_blocks: bool = False,
) -> str:
    """Convert GitHub-style markdown to Telegram MarkdownV2-friendly format.

    Applies telegramify_markdown, escapes nested backticks inside code blocks,
    adds `md` language tag to plain code blocks for Telegram rendering, and can
    optionally wrap fenced code blocks in spoilers.
    """
    formatted = markdownify(text)
    if strip_heading_icons:
        formatted = _strip_heading_icons(formatted)

    formatted = _escape_nested_backticks(formatted)
    formatted = _tag_plain_opening_fences(formatted)
    if collapse_code_blocks:
        formatted = collapse_fenced_code_blocks(formatted)
    return formatted


def collapse_fenced_code_blocks(text: str) -> str:
    """Wrap fenced code blocks into Telegram spoilers.

    This keeps snippets expandable in MarkdownV2 while preserving regular
    triple-backtick code fences inside the collapsed payload.
    """

    def _replace(match: re.Match[str]) -> str:
        lang = str(match.group(1) or "")
        body = str(match.group(2)).rstrip("\n")
        opening = f"{MARKDOWN_FENCE}{lang}" if lang else MARKDOWN_FENCE
        payload = f"{opening}\n{body}\n{MARKDOWN_FENCE}"
        return f"📦 *CODE BLOCK*\n\n||{payload}||"

    return re.sub(r"```([A-Za-z0-9_-]*)\n(.*?)```", _replace, text, flags=re.DOTALL)


def truncate_markdown_v2(text: str, max_chars: int, suffix: str) -> str:
    """Truncate MarkdownV2 text while keeping delimiters balanced."""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if len(suffix) >= max_chars:
        return suffix[:max_chars]

    budget = max_chars - len(suffix)
    truncated = _trim_with_balanced_markdown(text[:budget], budget)
    return f"{truncated}{suffix}"


def _trim_with_balanced_markdown(text: str, budget: int) -> str:
    """Trim text so required closing delimiters fit inside budget."""
    current = text[:budget]
    while True:
        if current.endswith("\\"):
            current = current[:-1]
        closers = _required_markdown_closers(current)
        if len(current) + len(closers) <= budget:
            return f"{current}{closers}"
        if not current:
            return closers[:budget]
        current = current[:-1]


def _required_markdown_closers(text: str) -> str:
    """Compute closers needed to finish inline/fenced/spoiler entities."""
    in_code_block = False
    in_inline_code = False
    in_spoiler = False
    i = 0

    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue

        if text[i : i + 3] == MARKDOWN_FENCE and not in_inline_code:
            in_code_block = not in_code_block
            i += 3
            continue

        if text[i : i + 2] == "||" and not in_code_block:
            in_spoiler = not in_spoiler
            i += 2
            continue

        if text[i] == MARKDOWN_INLINE_CODE and not in_code_block:
            in_inline_code = not in_inline_code
            i += 1
            continue

        i += 1

    closers: list[str] = []
    if in_inline_code:
        closers.append(MARKDOWN_INLINE_CODE)
    if in_code_block:
        if text and not text.endswith("\n"):
            closers.append("\n")
        closers.append(MARKDOWN_FENCE)
    if in_spoiler:
        closers.append("||")
    return "".join(closers)


def _tag_plain_opening_fences(text: str) -> str:
    """Add `md` tag to plain opening fences only (never closing fences)."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_code_block = False

    for line in lines:
        if line.startswith(MARKDOWN_FENCE):
            stripped = line.rstrip("\n")
            lang = stripped[3:]
            if not in_code_block:
                if lang == "":
                    newline = "\n" if line.endswith("\n") else ""
                    out.append("```md" + newline)
                else:
                    out.append(line)
                in_code_block = True
            else:
                out.append(line)
                in_code_block = False
            continue
        out.append(line)

    return "".join(out)


def _escape_nested_backticks(text: str) -> str:
    """Escape ``` inside code blocks to avoid breaking the outer fence."""

    def escape_nested_backticks(match: re.Match[str]) -> str:
        lang = str(match.group(1) or "")
        block_content = str(match.group(2))
        # Replace both raw and escaped fences (the latter can be added by markdownify)
        replacement = f"{MARKDOWN_INLINE_CODE}\u200b{MARKDOWN_INLINE_CODE}{MARKDOWN_INLINE_CODE}"
        escaped = block_content.replace(MARKDOWN_FENCE, replacement).replace(
            f"\\{MARKDOWN_INLINE_CODE}\\{MARKDOWN_INLINE_CODE}\\{MARKDOWN_INLINE_CODE}", replacement
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
