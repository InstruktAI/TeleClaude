# DOR Report: harmonize-agent-notifications

## Draft Assessment

### Gate 1: Intent & Success — PASS

- Problem: raw XML tags in notification messages leak to consumers.
- Outcome: clean messages + canonical event emission.
- Success criteria: 4 concrete, testable conditions defined in requirements.

### Gate 2: Scope & Size — PASS

- Atomic: touches 3 source files + 1 doc file.
- Single session feasible — no context exhaustion risk.
- No cross-cutting changes beyond the notification path + activity contract.

### Gate 3: Verification — PASS

- `make test` + `make lint` for regression.
- Demo scripts validate structural changes (tag stripping, field presence, mapping).
- Manual verification for end-to-end notification flow.

### Gate 4: Approach Known — PASS

- Pattern exists: `HOOK_TO_CANONICAL` mapping + `_emit_activity_event()` already used
  for 4 other hook types. This adds a 5th entry following the same pattern.
- Tag stripping is straightforward regex.
- Files and line numbers identified during research.

### Gate 5: Research — AUTO-PASS

- No third-party dependencies. All changes are internal to the TeleClaude daemon.

### Gate 6: Dependencies — PASS

- Depends on `ucap-cutover-parity-validation` — delivered.
- No external system dependencies.

### Gate 7: Integration Safety — PASS

- Additive changes only: new mapping entry, new field, new event emission.
- Existing notification path (tmux injection, remote forwarding, DB flag) unchanged.
- If canonical event emission fails, notification delivery still works (error isolation
  pattern already in `_emit_activity_event()`).

### Gate 8: Tooling Impact — AUTO-PASS

- No tooling or scaffolding changes.

## Assumptions

1. XML tag pattern is `<tag-name>...</tag-name>` (self-closing or wrapping).
   A broad regex stripping all XML-like tags is acceptable since notification messages
   are plain text that should never contain intentional XML.
2. The `message` field on `CanonicalActivityEvent` and `AgentActivityEvent` is additive
   and does not break existing consumers (they ignore unknown fields or use dataclass defaults).
3. Error hook (`error`) harmonization is intentionally out of scope — different semantic,
   different todo.

## Open Questions

None. All architectural decisions resolved during research.

## Corrections Applied

- Original requirements incorrectly described the notification flow as "leaking into the
  event stream." Corrected: notifications flow through `handle_notification()` →
  `notify_input_request()` (tmux injection), NOT through the activity event stream.
- Original plan included `error` → `agent_error` mapping. Removed: out of scope.
- Original plan did not include dependency graph or task-to-requirement tracing. Added.
