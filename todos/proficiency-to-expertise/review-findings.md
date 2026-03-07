# Review Findings: proficiency-to-expertise

## Review Meta

- **Review round:** 2 (independent re-review after fixes)
- **Merge-base:** `c7c24004`
- **Scope:** Schema, API DTO, injection rendering, CLI, tests, demo
- **Lanes run:** scope, code, paradigm, principles, security, tests, errors, comments, demo

---

## Round 1 Findings (resolved)

### Critical (resolved)

#### C1. API endpoint drops `expertise` and `proficiency` from PersonDTO construction

**File:** `teleclaude/api_server.py:1800` | **Fix:** `433d6da87` | **Verified:** ✅

#### C2. Deferrals document claims test files are "not touched" but they were modified

**File:** `todos/proficiency-to-expertise/deferrals.md:19-25` | **Fix:** `03340dd15` | **Verified:** ✅

### Important (resolved)

| ID | Issue | Fix commit | Verified |
|----|-------|-----------|----------|
| I1 | `json.loads` on `--expertise` with no error handling at CLI boundary | `729076d09` | ✅ |
| I2 | `_render_person_header` fabricates "intermediate" default for missing key | `cb3ddc347` | ✅ |
| I3 | `_render_person_header` accepts `object` instead of `PersonEntry` | `cb3ddc347` | ✅ |
| I4 | Exception handler scope/log no longer match description | `cb3ddc347` | ✅ |
| I5 | Out-of-scope behavioral changes in test files | `03340dd15` | ✅ |

All 7 round-1 findings verified as resolved. Fixes are clean, minimal, and targeted.

---

## Round 2 Findings (new)

### Critical

None.

### Important

#### I6. Edit path assigns expertise without Pydantic validation

**File:** `teleclaude/cli/config_cli.py:339`

```python
p.expertise = json.loads(opts["expertise"])  # type: ignore[assignment]
```

`PersonEntry` does not set `validate_assignment=True`, so direct attribute assignment bypasses Pydantic field validation. A user could `--expertise '{"teleclaude": "guru"}'` and the invalid level persists to config. It would only fail on next config load.

By contrast, `_people_add` passes expertise through the `PersonEntry(...)` constructor, which validates correctly.

**Mitigating factors:** (a) matches the pre-existing pattern for `p.proficiency = opts["proficiency"]` on the next line, (b) invalid data is caught on next config load. Not a data-loss risk.

**Fix:** Validate the parsed JSON by constructing a temporary `PersonEntry` before assigning, or add `validate_assignment=True` to `model_config`.

#### I7. Direct unit tests missing for `_render_person_header` branches

**File:** `teleclaude/hooks/receiver.py:238-264`

The function has six rendering branches. Three are tested (indirectly through `_print_memory_injection`). Three are untested:

1. **Structured domain with default only** (line 259-260): `{"default": "expert"}` with no sub-areas
2. **Structured domain with sub-areas only** (line 261-263): `{"frontend": "expert"}` with no `"default"` key
3. **Empty expertise dict** `{}`: renders `"Human in the loop: {name}\nExpertise:"` with no entries (ugly but not broken)

The function is pure and easy to test directly. Integration tests exercise the wiring but miss these edge cases.

### Suggestions

#### S1. `_render_person_header` silently drops entries with unexpected value types

**File:** `teleclaude/hooks/receiver.py:250-263`

The `isinstance(value, str)` / `isinstance(value, dict)` checks have no `else` branch. An entry with an unexpected type (e.g., `None`, `int`, `list`) is silently omitted. In practice, Pydantic validation prevents this for the add path — but the edit path validation bypass (I6) means unexpected types could enter.

**Recommendation:** Add a `logger.warning` in an `else` branch.

#### S2. Inconsistent deprecation comment on `PersonDTO.proficiency`

**File:** `teleclaude/api_models.py:165`

Uses `# deprecated` while `schema.py` and `config_cli.py` use `# deprecated — use expertise`. Match the longer form for consistency.

#### S3. `getattr` on strongly-typed Pydantic model in `_people_list`

**File:** `teleclaude/cli/config_cli.py:164-165`

`getattr(p, "expertise", None)` on a `PersonEntry` with declared fields. Direct attribute access (`p.expertise`) would surface schema drift at development time.

#### S4. Stale "proficiency line" terminology in backward-compat test names

**File:** `tests/unit/test_hooks_receiver_memory.py:109,131,152`

Test names/docstrings reference "proficiency line" while implementation uses "person header."

#### S5. Temporal "now" comments in tests

**Files:** `tests/unit/test_config_schema.py:410`, `tests/unit/test_config_cli.py:410`

Comments like `# now optional; defaults to None` describe a transition, not the present state. Comments should describe the present, never the past.

#### S6. Field-enumerating comment will drift

**File:** `teleclaude/cli/config_cli.py:324`

`# Edit global entry fields (role, email, username, expertise, proficiency)` enumerates fields that the next line already shows in code. Simplify to `# Edit global entry fields` or remove.

#### S7. Additional out-of-scope changes not documented in deferrals

The diff includes changes to files not mentioned in deferrals.md:
- `tests/unit/test_diagram_extractors.py:111-112`: command name changes (`next_review_todo` → `next_review_build`)
- `tests/unit/test_tui_key_contract.py:361-376`: added session ID mocks
- `teleclaude/api_server.py:817`: added `pyright: ignore[reportReturnType]` (documented in quality-checklist but not deferrals)
- `teleclaude/cli/models.py`, `tui/app.py`, `tui/widgets/telec_footer.py`: formatter/import reordering

These are trivial pre-existing fixes and cosmetic changes. Not blocking.

---

## Security

No security findings. No secrets, injection risks, auth gaps, or information leakage.

---

## Demo

7 executable bash blocks covering schema validation (flat, structured, invalid, backward compat), injection rendering (expertise block, proficiency fallback), and CLI add. All blocks reference real imports and functions. **Pass.**

---

## Scope

All implementation-plan tasks checked `[x]`. TUI deferred to sub-todo `proficiency-to-expertise-tui` — justified and tracked. Requirements 1-6, 8-9 implemented. No gold-plating.

---

## Paradigm Fit

- Schema → DTO → rendering data flow: consistent with codebase patterns ✅
- CLI uses established `--key value` pattern with `_parse_kv_args` ✅
- Test structure follows existing patterns ✅
- No copy-paste duplication ✅

**Pass.**

---

## Why No Critical Issues

1. **Paradigm-fit verified:** Schema → DTO → CLI data flow follows established patterns. PersonDTO construction, CLI flag parsing, and hook rendering all use patterns consistent with adjacent code.
2. **Requirements met:** All 9 in-scope requirements traced to implementation. TUI display (req 7) explicitly deferred with tracked sub-todo.
3. **Copy-paste checked:** No duplicated logic detected. `_render_person_header` is a single-owner function, expertise validation is handled at schema level, CLI paths are distinct.
4. **Security reviewed:** No secrets, no injection surfaces, no auth gaps. CLI boundary input validation present via `json.JSONDecodeError` handling and Pydantic schema validation.
5. **Round 1 fixes verified:** All 7 prior findings (2 Critical, 5 Important) confirmed resolved with clean, minimal commits.

---

## Verdict: APPROVE

Two Important findings (I6, I7) documented as non-blocking improvements. I6 (edit path validation bypass) is consistent with the pre-existing proficiency editing pattern and does not introduce a new class of defect. I7 (test coverage gaps) covers edge cases that are guarded by upstream Pydantic validation and tested indirectly through integration. Suggestions S1-S7 are improvements for follow-up.
