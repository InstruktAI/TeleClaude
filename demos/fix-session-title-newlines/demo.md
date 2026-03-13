# Demo: fix-session-title-newlines

## Validation

```bash
# Verify splitlines() fix is present in session_row.py
grep -n "splitlines" teleclaude/cli/tui/widgets/session_row.py
```

```bash
# Verify the slug highlight styling is present (permanent highlight + inversion)
grep -n "resolve_selection_bg_hex\|resolve_preview_bg_hex\|get_selection_fg_hex" teleclaude/cli/tui/widgets/session_row.py | grep -v "^Binary"
```

```bash
# Run the reproduction tests
.venv/bin/python -m pytest tests/unit/cli/tui/test_session_row.py -v
```

```bash
# Confirm all three test cases pass
.venv/bin/python -m pytest tests/unit/cli/tui/test_session_row.py -v --tb=short
```

## Guided Presentation

**1. Newline stripping (primary bug fix)**

Run the first validation block. You should see `splitlines()[0]` on line ~192
of `session_row.py`. This replaces the original `split("\n")[0]`, adding
coverage for `\r\n` (Windows), `\r` (old Mac), and Unicode line breaks.

Before the fix, a session title like:
```
/next-build rlf-peripherals

ADDITIONAL CONTEXT:
B…
```
would bleed across multiple lines in the collapsed row. The fix cuts at the
first line break regardless of origin.

**2. Slug permanent highlight**

Run the second validation block. You should see `resolve_selection_bg_hex`,
`resolve_preview_bg_hex`, and `get_selection_fg_hex` all referenced within
`_build_title_line()`. This confirms the worktree slug is now:
- Always highlighted (agent-themed `highlight` tier in normal state)
- Inverted (fg/bg swap) when the row is selected or previewed

**3. Reproduction tests**

Run the third and fourth validation blocks. All 3 tests should pass:
- `test_title_with_unix_newline_renders_first_line_only` — primary reproduction
- `test_title_with_crlf_newline_renders_first_line_only` — regression guard
- `test_title_that_is_only_newline_renders_empty_first_line` — edge case documentation
