# Review Findings: telegram-callback-payload-migration

## Verdict: APPROVE

Round 2 re-review after all 4 R1 findings were fixed. The migration is structurally sound, all
requirements are met, and no blocking issues remain.

---

## Round 1 — Resolved

All 4 Important findings from R1 were fixed and verified:

| # | Finding | Fix | Commit | Verified |
|---|---------|-----|--------|----------|
| 1 | Missing behavioral tests for callback dispatch logic | Added `TestCallbackDispatch` with 5 tests covering new payload, resume variant, legacy rewrite, unknown-agent warning, auto_command construction | `8090c833b` | Tests present at `test_telegram_menus.py:245-348`, all pass |
| 2 | Hardcoded string literals instead of `CallbackAction` enum values | `_build_heartbeat_keyboard` uses `CallbackAction.AGENT_SELECT.value`/`AGENT_RESUME_SELECT.value`; `_handle_agent_select` uses `CallbackAction.AGENT_RESUME_START`/`AGENT_START` | `532d6c3e2` | Confirmed at `telegram_adapter.py:1136,1140` and `callback_handlers.py:377` |
| 3 | Stale docstring with old format examples | Updated `_build_project_keyboard` docstring to `(e.g., "s", "as:claude", "ars:gemini")` | `532d6c3e2` | Confirmed at `telegram_adapter.py:1108` |
| 4 | Silent return on unknown agent should warn | Changed `logger.debug` to `logger.warning` at both locations | `532d6c3e2` | Confirmed at `callback_handlers.py:374,483` |

## Round 2 — New Findings

### Critical

None.

### Important

None.

### Suggestions

#### S1. Use `CallbackAction` enum values in `LEGACY_ACTION_MAP`

**Location:** `callback_handlers.py:62-75`
**Lane:** code-review

Map values use raw strings (`"asel"`, `"arsel"`, etc.) instead of `CallbackAction.*.value`.
Consistent with the R1 fix applied to the keyboard builder and handlers. However, the values
are immediately validated via `CallbackAction(action_raw)` at line 159, so the failure mode
is visible (ValueError + warning log) rather than silent divergence. Non-blocking.

#### S2. Add test for resume start auto_command construction

**Location:** `test_telegram_menus.py` (absent test)
**Lane:** test-analyzer

`test_agent_start_auto_command_construction` only exercises the non-resume path (`as:gemini:0`
produces `"agent gemini"`). The resume variant (`ars:gemini:0` should produce
`"agent_resume gemini"`) is untested. The resume dispatch routing is covered by
`test_resume_payload_dispatches_with_is_resume_true`, and the construction is a simple
one-line conditional. Non-blocking, but would improve confidence.

#### S3. Add test for legacy start payload dispatch

**Location:** `test_telegram_menus.py` (absent test)
**Lane:** test-analyzer

`test_legacy_csel_rewrites_and_dispatches` covers legacy *select* rewriting (`csel:bot`).
No equivalent test for legacy *start* rewriting (`c:0` to `as:claude:0`). The rewriting
logic is identical; the downstream handler differs. Non-blocking.

#### S4. Elevate new guard clause logging from debug to warning

**Location:** `callback_handlers.py:171-173,184-186`
**Lane:** silent-failure-hunter

The new `if not rest: logger.debug("AGENT_SELECT/START missing agent_name"); return` guards
use `debug` level. A missing agent name in a validated action payload is more significant
than routine debug noise. `warning` would be consistent with the R1 fix for unknown agents.

---

## Scope Verification

All requirements from `requirements.md` implemented in code:

- Generic `CallbackAction` enum values (`AGENT_SELECT`, `AGENT_RESUME_SELECT`, `AGENT_START`,
  `AGENT_RESUME_START`): confirmed
- Dynamic heartbeat keyboard via `get_enabled_agents()`: confirmed
- Legacy payload parsing via `LEGACY_ACTION_MAP`: confirmed
- New canonical `action:agent:arg` format: confirmed
- `event_map` and `mode_map` eliminated: confirmed
- Tests cover all categories: new format, legacy format, dynamic keyboard, auto_command,
  unknown agent rejection: confirmed

No gold-plating or unrequested features. Out-of-scope changes (telec_footer.py, core.py,
tts/manager.py, test_access_control.py, test_api_server.py) are formatting and pre-existing
test fixes, appropriately noted in the quality checklist.

## Paradigm-Fit

- Data flow uses existing `get_enabled_agents()` and `AgentName.from_str()` APIs. No bypasses.
- Component reuse: `_build_project_keyboard`, `_restore_heartbeat_menu`, `CommandMapper` all
  reused correctly.
- Pattern consistency: type narrowing, callback handler structure, and mixin contract all
  follow established codebase patterns.
- Local import of `get_enabled_agents` inside method body is consistent with deferred-import
  patterns used elsewhere in the file.

## Principle Violations

No violations found in changed code. Specifically checked:

- **Fallback/silent degradation:** New guard clauses log and return; no silent default
  substitution. The `LEGACY_ACTION_MAP` rewriting is an explicit backward-compat mechanism,
  not a hidden fallback.
- **DIP:** Adapter imports from core (correct direction). No core-to-adapter dependencies.
- **SRP:** Each handler has a single responsibility. Dispatch logic is clean routing.
- **YAGNI/KISS:** Implementation is minimal and focused. No premature abstractions.

## Security

- No secrets in diff
- No sensitive data in logs
- Input validation at boundary via `AgentName.from_str()`
- No injection vectors (callback data parsed as strings, indices int()-converted with try/except)
- Authorization checks present in all handlers
- Error messages do not leak internal info

## Demo

Demo artifact has 3 executable bash blocks exercising real imports and assertions. Commands,
flags, and expected outputs match the actual implementation. Demo is genuine, not fabricated.
No-demo marker not present (correctly — delivery has user-visible behavior changes).

## Zero-Finding Justification

No Important or Critical findings in R2.

1. **Paradigm-fit verified:** Dynamic keyboard follows existing `get_enabled_agents()` pattern;
   callback handler structure matches established mixin contract; deferred imports consistent.
2. **Requirements verified:** Each of the 7 success criteria traced to implementation and tests.
   All implementation-plan tasks checked. No deferrals.
3. **Copy-paste duplication checked:** No duplicated logic. `LEGACY_ACTION_MAP` is a data
   constant, not duplicated code. Handler patterns are consistent but each has distinct behavior.
4. **Security reviewed:** No secrets, no injection, authorization present, error messages safe.
5. **Test coverage verified:** 5 behavioral dispatch tests + 12 legacy map tests + 8 keyboard
   tests + 4 enum tests + 2 project keyboard tests = comprehensive coverage. All 3281 tests pass.
