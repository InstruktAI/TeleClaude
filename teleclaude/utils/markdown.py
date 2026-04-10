"""Markdown formatting utilities for Telegram MarkdownV2."""

import re
from dataclasses import dataclass
from typing import Protocol

from telegramify_markdown import markdownify as _markdownify

from teleclaude.constants import MARKDOWN_FENCE, MARKDOWN_INLINE_CODE


class MarkdownifyFn(Protocol):  # pylint: disable=too-few-public-methods
    """Callable protocol for HTML-to-markdown conversion."""

    def __call__(
        self,
        content: str,
        *,
        max_line_length: int = 0,
        normalize_whitespace: bool = False,
        latex_escape: bool = True,
    ) -> str: ...


markdownify: MarkdownifyFn = _markdownify


_STATE_CODE_BLOCK = "code_block"
_STATE_INLINE_CODE = "inline_code"
_STATE_SPOILER = "spoiler"
_STATE_BOLD = "bold"
_STATE_ITALIC = "italic"
_STATE_UNDERLINE = "underline"
_STATE_STRIKETHROUGH = "strikethrough"


@dataclass(frozen=True)
class MarkdownV2State:
    """Parser state for balanced MarkdownV2 chunking.

    stack:
        Open entity markers in open order. This preserves close/reopen order
        for nested entities across chunk boundaries.
    in_link_text:
        True when currently scanning ``[link text`` (before ``](``).
    link_url_depth:
        Parenthesis depth while scanning ``(link-url)``.
    """

    stack: tuple[str, ...] = ()
    in_link_text: bool = False
    link_url_depth: int = 0


MARKDOWN_V2_INITIAL_STATE = MarkdownV2State()


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


def _toggle_stack_marker(stack: list[str], marker: str) -> None:
    """Toggle marker on stack using strict top-of-stack matching."""
    if stack and stack[-1] == marker:
        stack.pop()
        return
    stack.append(marker)


def _consume_escaped_markdown_char(text: str, index: int) -> int | None:
    if text[index] != "\\":
        return None
    return index + 2


def _consume_markdown_link_state(
    text: str,
    index: int,
    *,
    in_link_text: bool,
    link_url_depth: int,
) -> tuple[int, bool, int] | None:
    if link_url_depth > 0:
        if text[index] == "(":
            link_url_depth += 1
        elif text[index] == ")":
            link_url_depth -= 1
        return index + 1, in_link_text, link_url_depth
    if not in_link_text:
        return None
    if text[index : index + 2] == "](":
        return index + 2, False, 1
    if text[index] == "]":
        return index + 1, False, 0
    return index + 1, True, 0


def _consume_markdown_code_state(text: str, index: int, stack: list[str]) -> int | None:
    in_code_block = bool(stack and stack[-1] == _STATE_CODE_BLOCK)
    if in_code_block:
        if text[index : index + 3] == MARKDOWN_FENCE:
            stack.pop()
            return index + 3
        return index + 1

    in_inline_code = bool(stack and stack[-1] == _STATE_INLINE_CODE)
    if in_inline_code:
        if text[index] == MARKDOWN_INLINE_CODE:
            stack.pop()
            return index + 1
        return index + 1

    if text[index : index + 3] == MARKDOWN_FENCE:
        stack.append(_STATE_CODE_BLOCK)
        return index + 3
    return None


def _consume_markdown_format_marker(text: str, index: int, stack: list[str]) -> int | None:  # pylint: disable=too-many-return-statements
    if text[index] == "[":
        return index + 1
    if text[index : index + 2] == "||":
        _toggle_stack_marker(stack, _STATE_SPOILER)
        return index + 2
    if text[index : index + 2] == "__":
        _toggle_stack_marker(stack, _STATE_UNDERLINE)
        return index + 2
    if text[index] == MARKDOWN_INLINE_CODE:
        stack.append(_STATE_INLINE_CODE)
        return index + 1
    if text[index] == "*":
        _toggle_stack_marker(stack, _STATE_BOLD)
        return index + 1
    if text[index] == "_":
        _toggle_stack_marker(stack, _STATE_ITALIC)
        return index + 1
    if text[index] == "~":
        _toggle_stack_marker(stack, _STATE_STRIKETHROUGH)
        return index + 1
    return None


def scan_markdown_v2_state(text: str, initial_state: MarkdownV2State = MARKDOWN_V2_INITIAL_STATE) -> MarkdownV2State:
    """Scan text and return MarkdownV2 parser state after consuming it."""
    stack = list(initial_state.stack)
    in_link_text = initial_state.in_link_text
    link_url_depth = initial_state.link_url_depth
    i = 0
    while i < len(text):
        escaped_index = _consume_escaped_markdown_char(text, i)
        if escaped_index is not None:
            i = escaped_index
            continue

        link_state = _consume_markdown_link_state(
            text,
            i,
            in_link_text=in_link_text,
            link_url_depth=link_url_depth,
        )
        if link_state is not None:
            i, in_link_text, link_url_depth = link_state
            continue

        code_index = _consume_markdown_code_state(text, i, stack)
        if code_index is not None:
            i = code_index
            continue

        format_index = _consume_markdown_format_marker(text, i, stack)
        if format_index is None:
            i += 1
            continue
        if text[i] == "[":
            in_link_text = True
        i = format_index

    return MarkdownV2State(
        stack=tuple(stack),
        in_link_text=in_link_text,
        link_url_depth=link_url_depth,
    )


def continuation_prefix_for_markdown_v2_state(state: MarkdownV2State) -> str:
    """Build opening markers needed to continue a previously closed chunk."""
    parts: list[str] = []
    for marker in state.stack:
        parts.append(_opening_marker_for_state(marker))
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
    if len(text) <= max_chars and not suffix:
        truncated, consumed_chars = _trim_with_balanced_markdown_with_consumed(text, max_chars)
        return truncated, consumed_chars
    if len(text) <= max_chars:
        return text, len(text)
    if len(suffix) >= max_chars:
        return suffix[:max_chars], 0

    budget = max_chars - len(suffix)
    truncated, consumed_chars = _trim_with_balanced_markdown_with_consumed(text[:budget], budget)
    return f"{truncated}{suffix}", consumed_chars


def leading_balanced_markdown_v2_entity_span(text: str, max_scan_chars: int = 512) -> int:
    """Return length of the first balanced leading MarkdownV2 entity span.

    Used by threaded chunking to avoid splitting small atomic entities
    (e.g. links, short styled fragments) across message boundaries.
    Returns 0 when no leading marker entity is complete within the scan window.
    """
    if not text:
        return 0

    opening_chars = {"[", "*", "_", "~", "`", "|"}
    if text[0] not in opening_chars:
        return 0

    saw_marker = False
    limit = min(len(text), max_scan_chars)
    for idx in range(1, limit + 1):
        if text[idx - 1] in opening_chars:
            saw_marker = True
        if not saw_marker:
            continue
        state = scan_markdown_v2_state(text[:idx])
        if state == MARKDOWN_V2_INITIAL_STATE:
            # If we just closed `[text]` and the next char starts a URL
            # section (`(`), keep scanning so links are treated atomically.
            if 0 < idx < len(text) and text[idx] == "(" and text[idx - 1] == "]":
                continue
            return idx

    return 0


def _trim_with_balanced_markdown_with_consumed(text: str, budget: int) -> tuple[str, int]:
    """Trim text and return balanced output plus consumed source chars."""
    current = text[:budget]
    while True:
        if current.endswith("\\"):
            current = current[:-1]

        state = scan_markdown_v2_state(current)
        # Splitting inside link entities is fragile in MarkdownV2; backtrack
        # until the boundary is outside any link text/url context.
        if state.in_link_text or state.link_url_depth > 0:
            if not current:
                return "", 0
            current = current[:-1]
            continue

        closers = _required_markdown_closers(current, state=state)
        if len(current) + len(closers) <= budget:
            return f"{current}{closers}", len(current)
        if not current:
            return closers[:budget], 0
        current = current[:-1]


def _required_markdown_closers(text: str, state: MarkdownV2State | None = None) -> str:
    """Compute closers needed to finish currently open MarkdownV2 entities."""
    resolved_state = state if state is not None else scan_markdown_v2_state(text)
    return _required_markdown_closers_from_state(text, resolved_state)


def _required_markdown_closers_from_state(text: str, state: MarkdownV2State) -> str:
    """Compute closers from a pre-scanned parser state."""
    # We intentionally do not auto-close links here; splitter backtracks before
    # link contexts so chunk boundaries avoid partial link entities.
    if state.in_link_text or state.link_url_depth > 0:
        return ""

    closers: list[str] = []
    for marker in reversed(state.stack):
        closers.append(_closing_marker_for_state(marker, text))
    return "".join(closers)


def _opening_marker_for_state(marker: str) -> str:  # pylint: disable=too-many-return-statements
    """Return opening marker string for a state token."""
    if marker == _STATE_SPOILER:
        return "||"
    if marker == _STATE_CODE_BLOCK:
        return f"{MARKDOWN_FENCE}\n"
    if marker == _STATE_INLINE_CODE:
        return MARKDOWN_INLINE_CODE
    if marker == _STATE_BOLD:
        return "*"
    if marker == _STATE_ITALIC:
        return "_"
    if marker == _STATE_UNDERLINE:
        return "__"
    if marker == _STATE_STRIKETHROUGH:
        return "~"
    return ""


def _closing_marker_for_state(marker: str, source_text: str) -> str:  # pylint: disable=too-many-return-statements
    """Return closing marker string for a state token."""
    if marker == _STATE_SPOILER:
        return "||"
    if marker == _STATE_INLINE_CODE:
        return MARKDOWN_INLINE_CODE
    if marker == _STATE_CODE_BLOCK:
        prefix = "\n" if source_text and not source_text.endswith("\n") else ""
        return f"{prefix}{MARKDOWN_FENCE}"
    if marker == _STATE_BOLD:
        return "*"
    if marker == _STATE_ITALIC:
        return "_"
    if marker == _STATE_UNDERLINE:
        return "__"
    if marker == _STATE_STRIKETHROUGH:
        return "~"
    return ""


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


# ===========================================================================
# GFM (GitHub-Flavoured Markdown) state machine
#
# Used by Discord (raw GFM, no conversion) and any future adapter that
# sends standard markdown.  Tracks: code-fence, inline-code, bold (``**``),
# strikethrough (``~~``), and spoiler (``||``).  The scanner is intentionally
# simpler than the MarkdownV2 one — GFM has no escape sequences relevant to
# splitting and no link-text / parenthesis-depth edge cases.
# ===========================================================================

_GFM_STATE_CODE_FENCE = "gfm_code_fence"
_GFM_STATE_BOLD = "gfm_bold"
_GFM_STATE_STRIKETHROUGH = "gfm_strikethrough"
_GFM_STATE_SPOILER = "gfm_spoiler"


@dataclass(frozen=True)
class GfmMarkdownState:
    """Parser state for balanced GFM chunking.

    stack:
        Open multi-line markers in open order, innermost last. Tracks code
        fences and toggle-style markers (bold, strikethrough, spoiler).
    open_inline_code_run:
        Length of an inline code backtick run that is still waiting for its
        matching closer at the end of the scanned text. Zero when not inside
        an inline code span. CommonMark inline code is handled with atomic
        lookahead matching: a run of N backticks closes at the next run of
        exactly N backticks. Spans with no closer in the current text carry
        the run length here so the next chunk can reopen with the same run.
    """

    stack: tuple[str, ...] = ()
    open_inline_code_run: int = 0


GFM_MARKDOWN_INITIAL_STATE = GfmMarkdownState()


def _at_line_start(text: str, index: int) -> bool:
    """Return True if *index* is at the start of a line in *text*."""
    return index == 0 or text[index - 1] == "\n"


def _backtick_run_length(text: str, index: int) -> int:
    """Return the number of consecutive backticks starting at *index*."""
    count = 0
    length = len(text)
    while index + count < length and text[index + count] == MARKDOWN_INLINE_CODE:
        count += 1
    return count


def _find_matching_backtick_run(text: str, start: int, run_length: int) -> int:
    """Return the index of the next backtick run of exactly *run_length*.

    Scans *text* from *start* forward. Returns -1 when no matching run exists.
    This is the CommonMark inline code closing rule: the closing run must be
    exactly the same length as the opening run.
    """
    i = start
    length = len(text)
    while i < length:
        if text[i] != MARKDOWN_INLINE_CODE:
            i += 1
            continue
        run = _backtick_run_length(text, i)
        if run == run_length:
            return i
        i += run
    return -1


def scan_gfm_state(  # pylint: disable=too-many-branches
    text: str, initial_state: GfmMarkdownState = GFM_MARKDOWN_INITIAL_STATE
) -> GfmMarkdownState:
    """Scan GFM text and return parser state after consuming it.

    Inline code spans are treated as atomic: a backtick run of length N is
    matched against the next run of exactly N in the remaining text. Found
    spans advance past the closer with no state change. Unmatched opening
    runs are carried as ``open_inline_code_run`` so the caller can reopen
    the span in the next chunk.

    Code fences must begin at the start of a line (CommonMark requirement).
    A fence mid-line is treated as an inline code run of 3 backticks.
    """
    stack = list(initial_state.stack)
    open_run = initial_state.open_inline_code_run
    length = len(text)
    i = 0

    # Resume: if we entered this scan already inside an open inline code span,
    # scan forward for the matching-length closer. If found, close the span;
    # otherwise the whole text is consumed inside the still-open span.
    if open_run > 0:
        close_idx = _find_matching_backtick_run(text, 0, open_run)
        if close_idx == -1:
            return GfmMarkdownState(stack=tuple(stack), open_inline_code_run=open_run)
        i = close_idx + open_run
        open_run = 0

    while i < length:
        in_fence = bool(stack and stack[-1] == _GFM_STATE_CODE_FENCE)

        if in_fence:
            # Closing fence must be at line start, 3+ backticks.
            if _at_line_start(text, i) and text[i] == MARKDOWN_INLINE_CODE:
                run = _backtick_run_length(text, i)
                if run >= 3:
                    stack.pop()
                    i += run
                    continue
            i += 1
            continue

        ch = text[i]

        # Opening code fence: 3+ backticks at line start.
        if ch == MARKDOWN_INLINE_CODE and _at_line_start(text, i):
            run = _backtick_run_length(text, i)
            if run >= 3:
                stack.append(_GFM_STATE_CODE_FENCE)
                i += run
                continue

        # Inline code: any backtick run with lookahead-matched closer.
        if ch == MARKDOWN_INLINE_CODE:
            run = _backtick_run_length(text, i)
            close_idx = _find_matching_backtick_run(text, i + run, run)
            if close_idx != -1:
                # Atomic span: advance past the closing run.
                i = close_idx + run
                continue
            # No closer in the remaining text — carry the run forward.
            open_run = run
            i += run
            continue

        # Toggle-style markers outside code context.
        if text[i : i + 2] == "**":
            _toggle_stack_marker(stack, _GFM_STATE_BOLD)
            i += 2
            continue
        if text[i : i + 2] == "~~":
            _toggle_stack_marker(stack, _GFM_STATE_STRIKETHROUGH)
            i += 2
            continue
        if text[i : i + 2] == "||":
            _toggle_stack_marker(stack, _GFM_STATE_SPOILER)
            i += 2
            continue

        i += 1

    return GfmMarkdownState(stack=tuple(stack), open_inline_code_run=open_run)


def _gfm_opening_marker(marker: str) -> str:
    if marker == _GFM_STATE_CODE_FENCE:
        return f"{MARKDOWN_FENCE}\n"
    if marker == _GFM_STATE_BOLD:
        return "**"
    if marker == _GFM_STATE_STRIKETHROUGH:
        return "~~"
    if marker == _GFM_STATE_SPOILER:
        return "||"
    return ""


def _gfm_closing_marker(marker: str, source_text: str) -> str:
    if marker == _GFM_STATE_CODE_FENCE:
        prefix = "\n" if source_text and not source_text.endswith("\n") else ""
        return f"{prefix}{MARKDOWN_FENCE}"
    if marker == _GFM_STATE_BOLD:
        return "**"
    if marker == _GFM_STATE_STRIKETHROUGH:
        return "~~"
    if marker == _GFM_STATE_SPOILER:
        return "||"
    return ""


def continuation_prefix_for_gfm_state(state: GfmMarkdownState) -> str:
    """Build GFM opening markers needed to continue a previously closed chunk."""
    parts = [_gfm_opening_marker(m) for m in state.stack]
    if state.open_inline_code_run > 0:
        parts.append(MARKDOWN_INLINE_CODE * state.open_inline_code_run)
    return "".join(parts)


def _gfm_closers(text: str, state: GfmMarkdownState) -> str:
    # Close innermost first: inline code (if open) before stacked markers.
    parts: list[str] = []
    if state.open_inline_code_run > 0:
        parts.append(MARKDOWN_INLINE_CODE * state.open_inline_code_run)
    parts.extend(_gfm_closing_marker(m, text) for m in reversed(state.stack))
    return "".join(parts)


def _seek_word_boundary(text: str) -> str:
    """Trim *text* to the last whitespace boundary (80% threshold).

    If a whitespace position exists in the last 20% of the text, trim there
    to avoid splitting mid-word.  Inside code fences or very short strings
    the caller should skip this step.
    """
    last_space = text.rfind(" ")
    if last_space > len(text) * 0.8:
        return text[:last_space]
    last_nl = text.rfind("\n")
    if last_nl > len(text) * 0.8:
        return text[:last_nl]
    return text


def _trim_gfm_balanced(text: str, budget: int) -> tuple[str, int]:
    """Trim GFM text to *budget* chars while keeping markers balanced."""
    current = text[:budget]
    while True:
        state = scan_gfm_state(current)
        if not state.stack and state.open_inline_code_run == 0:
            # No open markers — prefer a word boundary.
            current = _seek_word_boundary(current)
            return current, len(current)
        closers = _gfm_closers(current, state)
        if len(current) + len(closers) <= budget:
            # Markers will be closed — seek word boundary only when outside any
            # code context (fence or inline code span).
            in_code = state.open_inline_code_run > 0 or any(m == _GFM_STATE_CODE_FENCE for m in state.stack)
            if not in_code:
                trimmed = _seek_word_boundary(current)
                if len(trimmed) + len(closers) <= budget and trimmed:
                    closers = _gfm_closers(trimmed, scan_gfm_state(trimmed))
                    return f"{trimmed}{closers}", len(trimmed)
            return f"{current}{closers}", len(current)
        if not current:
            return closers[:budget], 0
        current = current[:-1]


def truncate_gfm_with_consumed(text: str, max_chars: int, suffix: str) -> tuple[str, int]:
    """Truncate GFM text to *max_chars* keeping markers balanced.

    Returns (truncated_text, consumed_source_chars).  The consumed count
    excludes any balancing closers or suffix appended during truncation.
    """
    if max_chars <= 0:
        return "", 0
    if len(text) <= max_chars and not suffix:
        return _trim_gfm_balanced(text, max_chars)
    if len(text) <= max_chars:
        return text, len(text)
    if len(suffix) >= max_chars:
        return suffix[:max_chars], 0
    budget = max_chars - len(suffix)
    truncated, consumed = _trim_gfm_balanced(text[:budget], budget)
    return f"{truncated}{suffix}", consumed


# ===========================================================================
# WhatsApp markdown state machine
# ===========================================================================
# Used after _convert_markdown_for_platform converts GFM → WhatsApp dialect.
# Tracks: code-block (```), bold (*), italic (_), strikethrough (~).
# Single-char markers (*/_/~) toggle open/closed symmetrically.
# ===========================================================================

_WA_STATE_CODE_BLOCK = "wa_code_block"
_WA_STATE_BOLD = "wa_bold"
_WA_STATE_ITALIC = "wa_italic"
_WA_STATE_STRIKETHROUGH = "wa_strikethrough"


@dataclass(frozen=True)
class WhatsAppMarkdownState:
    """Parser state for balanced WhatsApp markdown chunking.

    stack:
        Open entity markers in open order, innermost last.
        Preserves close/reopen order across chunk boundaries.
    """

    stack: tuple[str, ...] = ()


WA_MARKDOWN_INITIAL_STATE = WhatsAppMarkdownState()


def _scan_wa_token(text: str, index: int, stack: list[str]) -> int:  # pylint: disable=too-many-return-statements
    """Consume one WhatsApp token at *index*, mutating *stack*. Returns new index."""
    in_code = bool(stack and stack[-1] == _WA_STATE_CODE_BLOCK)
    if in_code:
        if text[index : index + 3] == MARKDOWN_FENCE:
            stack.pop()
            return index + 3
        return index + 1  # inside code block — skip char verbatim

    # Not inside a code block — process format markers (longest match first).
    if text[index : index + 3] == MARKDOWN_FENCE:
        stack.append(_WA_STATE_CODE_BLOCK)
        return index + 3
    if text[index] == "*":
        _toggle_stack_marker(stack, _WA_STATE_BOLD)
        return index + 1
    if text[index] == "_":
        _toggle_stack_marker(stack, _WA_STATE_ITALIC)
        return index + 1
    if text[index] == "~":
        _toggle_stack_marker(stack, _WA_STATE_STRIKETHROUGH)
        return index + 1
    return index + 1  # plain character


def scan_wa_state(text: str, initial_state: WhatsAppMarkdownState = WA_MARKDOWN_INITIAL_STATE) -> WhatsAppMarkdownState:
    """Scan WhatsApp markdown text and return parser state after consuming it."""
    stack = list(initial_state.stack)
    i = 0
    while i < len(text):
        i = _scan_wa_token(text, i, stack)
    return WhatsAppMarkdownState(stack=tuple(stack))


def _wa_opening_marker(marker: str) -> str:
    if marker == _WA_STATE_CODE_BLOCK:
        return f"{MARKDOWN_FENCE}\n"
    if marker == _WA_STATE_BOLD:
        return "*"
    if marker == _WA_STATE_ITALIC:
        return "_"
    if marker == _WA_STATE_STRIKETHROUGH:
        return "~"
    return ""


def _wa_closing_marker(marker: str, source_text: str) -> str:
    if marker == _WA_STATE_CODE_BLOCK:
        prefix = "\n" if source_text and not source_text.endswith("\n") else ""
        return f"{prefix}{MARKDOWN_FENCE}"
    if marker == _WA_STATE_BOLD:
        return "*"
    if marker == _WA_STATE_ITALIC:
        return "_"
    if marker == _WA_STATE_STRIKETHROUGH:
        return "~"
    return ""


def continuation_prefix_for_wa_state(state: WhatsAppMarkdownState) -> str:
    """Build WhatsApp opening markers needed to continue a previously closed chunk."""
    return "".join(_wa_opening_marker(m) for m in state.stack)


def _wa_closers(text: str, state: WhatsAppMarkdownState) -> str:
    return "".join(_wa_closing_marker(m, text) for m in reversed(state.stack))


def _trim_wa_balanced(text: str, budget: int) -> tuple[str, int]:
    """Trim WhatsApp markdown text to *budget* chars while keeping markers balanced."""
    current = text[:budget]
    while True:
        state = scan_wa_state(current)
        if not state.stack:
            current = _seek_word_boundary(current)
            return current, len(current)
        closers = _wa_closers(current, state)
        if len(current) + len(closers) <= budget:
            in_code = any(m == _WA_STATE_CODE_BLOCK for m in state.stack)
            if not in_code:
                trimmed = _seek_word_boundary(current)
                if len(trimmed) + len(closers) <= budget and trimmed:
                    closers = _wa_closers(trimmed, scan_wa_state(trimmed))
                    return f"{trimmed}{closers}", len(trimmed)
            return f"{current}{closers}", len(current)
        if not current:
            return closers[:budget], 0
        current = current[:-1]


def truncate_wa_with_consumed(text: str, max_chars: int, suffix: str) -> tuple[str, int]:
    """Truncate WhatsApp markdown text to *max_chars* keeping markers balanced.

    Returns (truncated_text, consumed_source_chars).  The consumed count
    excludes any balancing closers or suffix appended during truncation.
    """
    if max_chars <= 0:
        return "", 0
    if len(text) <= max_chars and not suffix:
        return _trim_wa_balanced(text, max_chars)
    if len(text) <= max_chars:
        return text, len(text)
    if len(suffix) >= max_chars:
        return suffix[:max_chars], 0
    budget = max_chars - len(suffix)
    truncated, consumed = _trim_wa_balanced(text[:budget], budget)
    return f"{truncated}{suffix}", consumed


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


def discordify_markdown(text: str) -> str:
    """Normalize generic markdown into Discord-friendly text.

    Discord supports a useful subset of markdown, but not custom link syntax.
    Convert markdown links into readable plain-text references while preserving
    common formatting that Discord already renders well.
    """
    converted = text
    converted = re.sub(
        r"!\[([^\]]*)\]\(([^)]+)\)", lambda m: f"{m.group(1)}: {m.group(2)}" if m.group(1) else m.group(2), converted
    )

    def _replace_link(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        target = match.group(2).strip()
        if target.startswith("/"):
            return f"`{label}`: `{target}`" if label else f"`{target}`"
        return f"{label}: {target}" if label else target

    converted = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _replace_link, converted)
    return converted
