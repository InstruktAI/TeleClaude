# Review Findings - ucap-tui-adapter-alignment

## Verdict: REQUEST CHANGES

## Summary

The core implementation is well-structured: `canonical_type` is correctly threaded from `AgentActivityEventDTO` through `AgentActivity` message to the `on_agent_activity` handler. The old `activity_type`-based bypass paths are fully removed. The `HOOK_TO_CANONICAL` mapping and `serialize_activity_event` are solid. The paradigm fit is correct — the WS event → DTO → Message → handler chain follows established data flow patterns.

Two findings require changes before approval.

---

## Critical

None.

## Important

### 1. Warning log missing structured `extra` fields — R4 violation

**File:** `teleclaude/cli/tui/app.py:542-546`

The debug log at line 535 correctly populates `extra={"lane": "tui", "canonical_type": canonical, "session_id": ...}` (satisfying R4). However, the warning log for the `canonical is None` path omits the `extra` dict entirely:

```python
logger.warning(
    "tui lane: AgentActivity missing canonical_type lane=tui hook_type=%s session=%s",
    message.activity_type,
    message.session_id[:8] if message.session_id else "",
    # No extra= here — R4 structured fields absent
)
```

R4 requires TUI lane logs to carry `lane` and `canonical_type` in structured fields. The `None` case is exactly the signal downstream metrics/alerting needs.

**Fix:** Add `extra={"lane": "tui", "canonical_type": None, "session_id": message.session_id}`.

### 2. `on_agent_activity` handler dispatch logic is entirely untested

**File:** `tests/unit/test_threaded_output_updates.py`

The 8 new tests cover:

- `AgentActivity` message attribute storage (4 tests) — correct but tests data holding, not behavior
- `serialize_activity_event` canonical mappings (3 tests) — duplicates coverage already in `test_activity_contract.py`
- Observability fields on `CanonicalActivityEvent` (1 test) — also duplicates `test_activity_contract.py`

None of the tests exercise the rewritten `on_agent_activity` handler itself — the highest-risk changed code. Untested paths:

- `canonical is None` → early return, no `sessions_view` calls
- `canonical == "user_prompt_submit"` → `clear_active_tool` + `set_input_highlight`
- `canonical == "agent_output_stop"` → `clear_active_tool` + `set_output_highlight` with summary
- `canonical == "agent_output_update"` with `tool_name` → preview-stripping logic at lines 557-559
- `canonical == "agent_output_update"` without `tool_name` → `clear_active_tool`
- Unknown `canonical_type` → falls through silently (intentional?)

Acceptance criterion 4 states "TUI-focused tests validate canonical contract path and regressions." The handler IS the canonical contract path for TUI. The existing tests validate upstream (serializer) and data transport (message class), but not the dispatch behavior.

The preview-stripping logic (`if preview.startswith(message.tool_name): preview = preview[len(...):]`) has edge cases worth covering: tool_preview == tool_name (empty remainder), tool_preview with different prefix, etc.

**Fix:** Add handler-level tests. Either use a mocked `SessionsView` injected into the handler, or extract the dispatch logic into a testable pure function.

---

## Suggestions

### 3. Serializer tests duplicate `test_activity_contract.py`

Tests 5-8 (lines 398-459) exercise `serialize_activity_event` directly. The dedicated `test_activity_contract.py` already covers these exact mappings more completely (parametrized across all hook types, validation failures, routing metadata, optional fields). The duplication inflates maintenance cost without differentiated regression value.

**Suggestion:** Remove or relocate these to their natural home in `test_activity_contract.py` if any gap is identified there. Replace them with handler-level tests that actually exercise the TUI dispatch.

### 4. Inline imports inconsistent with file convention

Tests 1-8 use inline `from ... import` inside each function body. All pre-existing tests in this file use top-level imports. Neither `AgentActivity` nor `serialize_activity_event` are heavy imports requiring deferral.

**Suggestion:** Hoist to module-level imports for consistency.

---

## Paradigm-Fit Assessment

1. **Data flow**: Correct. The implementation follows the established WS event → DTO model → Textual Message → handler pattern without introducing any bypass.
2. **Component reuse**: Correct. `AgentActivity` message class was extended (not copied), `on_agent_activity` was refactored in place.
3. **Pattern consistency**: Correct. The handler structure matches the sibling handlers in `app.py`. Structured logging follows the `instrukt_ai_logging` pattern with `extra` dicts.

---

## Requirement Verification

| Requirement                        | Status        | Evidence                                                                                |
| ---------------------------------- | ------------- | --------------------------------------------------------------------------------------- |
| R1: Canonical contract consumption | Met           | `on_agent_activity` dispatches on `canonical_type`, not `activity_type`                 |
| R2: Bypass removal                 | Met           | Old `activity_type` branches removed; `canonical is None` guard prevents untyped events |
| R3: Presentation boundary          | Met           | Tool preview formatting stays in TUI handler; canonical payload is not mutated          |
| R4: Observability parity           | Partially met | Debug log has structured fields; warning log (finding #1) does not                      |

## Build Checklist Validation

- Implementation plan tasks: All checked ✓
- Build section in quality-checklist: All checked ✓
- Commits exist: `ae6b1f0c` (build phase), `0393dad6` (feat) ✓
- No deferrals.md: ✓

## Review Round

1 of 3.
