# Demo: slug-helper

## Validation

```bash
# Verify the module is importable and exports the expected symbols
python -c "from teleclaude.slug import SLUG_PATTERN, validate_slug, normalize_slug, ensure_unique_slug; print('OK')"
```

```bash
# Verify no duplicate SLUG_PATTERN definitions (only slug.py owns it)
grep -rn "SLUG_PATTERN = re.compile" teleclaude/ | grep -v slug.py | wc -l | xargs test 0 -eq
```

```bash
# Verify no inline slug normalization in telec.py CLI handlers
grep -n 're.sub.*a-z0-9' teleclaude/cli/telec.py | wc -l | xargs test 0 -eq
```

```bash
# Verify tests pass
make test
```

## Guided Presentation

### Step 1: The new module

Open `teleclaude/slug.py`. Observe four exports: `SLUG_PATTERN`, `validate_slug`,
`normalize_slug`, `ensure_unique_slug`. Each does one thing. The regex lives here
and nowhere else.

### Step 2: Callers use the shared module

Open `teleclaude/todo_scaffold.py`. Note it imports from `teleclaude.slug` and
no longer defines `SLUG_PATTERN` or inline validation. `create_todo_skeleton` calls
`ensure_unique_slug` — no more `FileExistsError` on collision, it auto-suffixes.

Open `teleclaude/content_scaffold.py`. `_derive_slug` still owns the word-extraction
logic but delegates character-level conversion to `normalize_slug`. The counter-suffix
loop in `create_content_inbox_entry` is replaced by `ensure_unique_slug`.

Open `teleclaude/cli/telec.py`. `_handle_bugs_report` and `_handle_content_dump`
call `normalize_slug` instead of inline regex substitution.

### Step 3: Consistency proof

Run `grep -rn "re.sub.*a-z0-9" teleclaude/` and observe only `slug.py`,
`blocked_followup.py` (out of scope — domain-specific), and `roadmap.py`
(out of scope — heading conversion).

### Step 4: Test coverage

Run `make test`. All existing tests pass. New tests in `test_slug.py` cover
validation, normalization, and uniqueness edge cases.
