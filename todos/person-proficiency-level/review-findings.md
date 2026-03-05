# Review Findings: person-proficiency-level

## Verdict: APPROVE

---

## Critical

None.

---

## Important

### 1. Stale debug log message after extending the try block — `receiver.py:265-266`

**Location:** `teleclaude/hooks/receiver.py:265-266`

The broad `except Exception` block previously covered only identity key derivation. The new proficiency person-lookup code has been added inside the same block. The debug log message still reads:

```
"Identity key derivation failed for session %s"
```

If the exception originates from the person lookup (e.g., config list access fails), the logged message is factually wrong. This will mislead future debugging.

**Remediation:** Update the log message to cover both operations, e.g.:
```python
logger.debug("Session context resolution failed for session %s", (session_id or "")[:8])
```

---

## Suggestions

### 1. Unnecessary `getattr` fallback on Pydantic model — multiple sites

**Locations:**
- `teleclaude/cli/config_cli.py:159`: `getattr(p, "proficiency", "intermediate")`
- `teleclaude/hooks/receiver.py:263`: `getattr(person, "proficiency", "intermediate")`
- `teleclaude/cli/tui/views/config.py:931`: `getattr(person, 'proficiency', 'intermediate')`

`PersonEntry` is a Pydantic model with `proficiency` declared as a field with a default. The attribute is always present; `getattr` with a fallback is unnecessary and slightly misleading (implies the field might be absent). Could simplify to `person.proficiency` / `p.proficiency` at all three sites.

Not a blocker — the fallback value matches the declared default, so behavior is identical.

---

## Paradigm Fit Assessment

- **Data flow:** Uses `config.people` (established config access path) and `db_session.get(db_models.Session, session_id)` (established DB pattern). No bypasses.
- **Component reuse:** Follows existing patterns in `_render_people()` for TUI rendering and `PersonInfo` for CLI JSON output. No copy-paste duplication detected.
- **Pattern consistency:** CLI flag handling, Pydantic field declaration, and injection prepend pattern all align with adjacent code.

---

## Requirements Traceability

| Requirement | Status |
|---|---|
| `proficiency` field on `PersonEntry` with default `"intermediate"` | ✅ `config/schema.py:129` |
| Invalid values rejected (Pydantic) | ✅ `Literal` type + test |
| `_print_memory_injection()` prepends `Human in the loop: {name} ({proficiency})` | ✅ `receiver.py:272-273` |
| No injection when no email / no match | ✅ guarded by `if human_email:` + `if person:` |
| `--proficiency` flag on `people add` | ✅ `config_cli.py:215` |
| `--proficiency` flag on `people edit` | ✅ `config_cli.py:326-327` |
| `people list --json` includes `proficiency` | ✅ `PersonInfo.proficiency` + `_people_list()` |
| `PersonDTO` serializes proficiency | ✅ `api_models.py:163` |
| TUI people tab shows proficiency | ✅ `config.py:931` |
| Unit tests for all above | ✅ `test_config_schema.py`, `test_hooks_receiver_memory.py`, `test_config_cli.py` |

---

## Demo Artifact

7 executable blocks. All commands and flags (`PersonEntry`, `telec config people add/edit/list/remove`) exist in the codebase and match the implementation. Expected outputs are plausible and domain-specific. No fabricated flags or stubs detected.

Session injection demo (step 3 in guided presentation) is text-only — acceptable since it requires a live running session.

---

## Test Coverage

- Schema: default, valid values loop, invalid value rejection — complete.
- Injection: proficiency prepended with memory, proficiency alone without memory, no match → no proficiency line — complete; all three behavioral branches covered.
- CLI add with proficiency, CLI edit with proficiency, list JSON includes field — complete.
- All tests are behavioral (no prose-lock assertions).

---

## Manual Verification

Full automated test coverage for all user-visible behavioral changes. TUI rendering not directly testable in unit environment (no display); code path is simple append and visually correct. No blocking manual verification gap.
