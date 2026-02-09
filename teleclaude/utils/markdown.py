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


# (in_code_block, in_inline_code, in_spoiler)
MarkdownV2State = tuple[bool, bool, bool]


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


def escape_markdown_v2_preformatted(text: str) -> str:
    """Escape payload for Telegram MarkdownV2 code/pre entities.

    Telegram requires backslash and backtick to be escaped inside `code` and
    `pre` entities.
    """
    return text.replace("\\", "\\\\").replace(MARKDOWN_INLINE_CODE, f"\\{MARKDOWN_INLINE_CODE}")


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
    else:
        # Strip spurious || markers introduced by telegramify-markdown bug.
        # GitHub markdown has no spoiler syntax, so any || in output is spurious.
        formatted = formatted.replace("||", "")
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


def scan_markdown_v2_state(text: str, initial_state: MarkdownV2State = (False, False, False)) -> MarkdownV2State:
    """Scan text and return MarkdownV2 parser state after consuming it."""
    in_code_block, in_inline_code, in_spoiler = initial_state
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

    return in_code_block, in_inline_code, in_spoiler


def continuation_prefix_for_markdown_v2_state(state: MarkdownV2State) -> str:
    """Build opening markers needed to continue a previously closed chunk."""
    in_code_block, in_inline_code, in_spoiler = state
    parts: list[str] = []
    if in_spoiler:
        parts.append("||")
    if in_code_block:
        # Use newline to force fenced-code body (not language tag parsing).
        parts.append(f"{MARKDOWN_FENCE}\n")
    if in_inline_code:
        parts.append(MARKDOWN_INLINE_CODE)
    return "".join(parts)


def truncate_markdown_v2(text: str, max_chars: int, suffix: str) -> str:
    """Truncate MarkdownV2 text while keeping delimiters balanced."""
    truncated, _consumed_chars = truncate_markdown_v2_with_consumed(text, max_chars=max_chars, suffix=suffix)
    return truncated


def truncate_markdown_v2_by_bytes(text: str, max_bytes: int, suffix: str) -> str:
    """Truncate MarkdownV2 text to a UTF-8 byte budget.

    Uses binary search over character budgets and the balanced-char truncator
    to preserve MarkdownV2 entity integrity while honoring a byte ceiling.
    """
    if max_bytes <= 0:
        return ""
    if len(text.encode("utf-8")) <= max_bytes:
        return text

    low = 0
    high = len(text)
    best = ""
    while low <= high:
        mid = (low + high) // 2
        candidate = truncate_markdown_v2(text, max_chars=mid, suffix=suffix)
        candidate_bytes = len(candidate.encode("utf-8"))
        if candidate_bytes <= max_bytes:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1

    if best:
        return best

    # Fallback for extreme tiny budgets where even balanced truncation cannot fit.
    raw = suffix if suffix else text
    clipped = raw
    while clipped and len(clipped.encode("utf-8")) > max_bytes:
        clipped = clipped[:-1]
    return clipped


def truncate_markdown_v2_with_consumed(text: str, max_chars: int, suffix: str) -> tuple[str, int]:
    """Truncate MarkdownV2 text and return rendered text plus consumed source chars.

    The consumed character count only includes characters taken from ``text``.
    Any balancing closers or ``suffix`` added during truncation are excluded.
    """
    if max_chars <= 0:
        return "", 0
    if len(text) <= max_chars:
        return text, len(text)
    if len(suffix) >= max_chars:
        return suffix[:max_chars], 0

    budget = max_chars - len(suffix)
    truncated, consumed_chars = _trim_with_balanced_markdown_with_consumed(text[:budget], budget)
    return f"{truncated}{suffix}", consumed_chars


def _trim_with_balanced_markdown_with_consumed(text: str, budget: int) -> tuple[str, int]:
    """Trim text and return balanced output plus consumed source chars."""
    current = text[:budget]
    while True:
        if current.endswith("\\"):
            current = current[:-1]
        closers = _required_markdown_closers(current)
        if len(current) + len(closers) <= budget:
            return f"{current}{closers}", len(current)
        if not current:
            return closers[:budget], 0
        current = current[:-1]


def _required_markdown_closers(text: str) -> str:
    """Compute closers needed to finish inline/fenced/spoiler entities."""
    in_code_block, in_inline_code, in_spoiler = scan_markdown_v2_state(text)

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
