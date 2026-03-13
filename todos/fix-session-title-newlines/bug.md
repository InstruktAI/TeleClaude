# Bug: 

## Symptom

I see this in the TUI:

[2.1.1] ▼ claude/fast rlf-peripherals  "/next-build rlf-peripherals

 ADDITIONAL CONTEXT:
 B…"

So this is incorrect. We don't want new lines to be taken. So it will be either cut off after the maximum amount of characters for the title is reached, or any new line is found. Do you understand? 

use telec docs index to read all that you need and not assume anything

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-13

## Investigation

Traced to `teleclaude/cli/tui/widgets/session_row.py`, `_build_title_line()`.

Two issues found:

1. **Newline in titles:** The `title` string from `session.title` was passed directly to the length-truncation logic with no newline stripping. Textual's `Text` renderer treats `\n` as a real line break, causing multi-line bleed in the collapsed row.

2. **Slug not highlighted:** The slug (worktree name) was styled with `resolve_style(agent, "normal")` — plain, unstyled text. No permanent visual distinction. Additionally, when the row was selected/previewed, the slug simply inherited the full row style, blending in instead of standing out.

## Root Cause

1. No `\n` stripping before title display — first newline and everything after it was rendered as additional lines.
2. Slug styling used the wrong tier (`normal` instead of `highlight`) and had no inversion logic for selected/previewed rows.

## Fix Applied

**File:** `teleclaude/cli/tui/widgets/session_row.py`, `_build_title_line()`

1. **Newline stripping:** `title = (self.session.title or "(untitled)").split("\n")[0]` — takes only the first line before applying length truncation.

2. **Permanent slug highlight:**
   - Normal state: `resolve_style(agent, self._tier("highlight"))` — bold, max-contrast text, no background.
   - Selected row: inverted badge — `Style(color=resolve_selection_bg_hex(agent), bgcolor=get_selection_fg_hex(), bold=True)` — swaps the row's fg/bg.
   - Previewed row: same inversion with `resolve_preview_bg_hex(agent)` — slightly more muted, matching the preview palette.
   All colors derived from existing theme primitives already imported in the file.
