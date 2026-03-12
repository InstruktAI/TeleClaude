# Review Findings: fix-integrator-spawn-broken-integration-brid

## Resolved During Review

**`teleclaude/core/db.py` — `import dataclasses` inside method body (auto-remediated)**

The new `_serialize_session_metadata` method introduced `import dataclasses` inside the method
body (line 106), violating the "all imports at module top level" linting policy. The
pre-existing `import dataclasses` in `api_models.py` correctly demonstrates the expected
pattern. Fixed by moving `import dataclasses` to the top of `db.py` with the other stdlib
imports and removing the inline import.

---

## Important

### 1. No tests for the core fix or new behaviour

**Location:** `teleclaude/core/integration_bridge.py`, `teleclaude/core/command_service.py`,
`teleclaude/core/models.py`

**Finding:** Zero test coverage for the code paths introduced in this fix:

- `spawn_integrator_session` — the function that contained the bug. No test verifies
  the new behaviour (direct `run_slash_command` call) or that the guard check works
  correctly via `db.list_sessions()`.
- `CommandService.run_slash_command` — the new daemon-internal spawning method has no
  unit test. There is no test verifying that `COMMAND_ROLE_MAP` produces the correct
  `SessionMetadata`, or that `auto_command` is built correctly.
- `SessionMetadata` serialization round-trips — `_serialize_session_metadata`,
  `_to_core_session`, `Session.to_dict()`/`from_dict()`, and `SessionSnapshot.from_dict()`
  all gained new code paths that are untested. A malformed JSON row or unknown key in the
  DB could silently produce `None` instead of raising.

The existing 39 tests pass but cover none of the changed behaviour. Per the testing policy,
new functionality requires corresponding tests.

**Required:** Add unit tests covering:
- `spawn_integrator_session` with a mock `CommandService` — guard branch (already running)
  and spawn branch.
- `CommandService.run_slash_command` with a mock `create_session` — verify `SessionMetadata`
  fields and `auto_command` format.
- `SessionMetadata` serialization in `Db._serialize_session_metadata` and deserialization
  in `_to_core_session`.

### 2. Dead code loop in `agent_coordinator._resolve_hook_actor_name`

**Location:** `teleclaude/core/agent_coordinator.py:188-192`

**Finding:**

```python
metadata: dict[str, object] = {}
for key in ("actor_name", "user_name", "display_name", "username", "name"):
    resolved = _coerce_nonempty_str(metadata.get(key))
    if resolved:
        return resolved
```

`metadata` is permanently `{}`, so the loop body never executes. The old code used
`isinstance(session.session_metadata, Mapping)` to populate `metadata`, but now that
`session_metadata` is a typed `SessionMetadata` dataclass (not a `Mapping`), the condition
was always `False` in practice. The removal of the guard was correct per the bug description
("actor name fields were never in `SessionMetadata`"), but the dead loop should be removed
rather than left as unreachable iteration.

This is a KISS violation: three lines of code that produce no behaviour and will confuse
future readers about whether actor-name resolution from session metadata was intentionally
disabled or is expected to work.

**Required:** Remove the dead loop entirely. The function body should start directly with
`ui_meta = session.get_metadata().get_ui()`.

---

## Suggestions

### S1. Lazy imports in `run_slash_command` lack circular-import annotation

**Location:** `teleclaude/core/command_service.py:173-175`

The three imports inside `run_slash_command` follow the pre-existing pattern in
`command_service.py` (line 104) and in `db.py` (dozens of lazy SQLAlchemy imports), which
establishes that lazy imports are the project convention for circular-import avoidance in
this module. However, per the linting policy, suppressions or deviations should be
documented with a short comment. A single line comment like
`# deferred import — avoids circular dependency with command_mapper/models` would satisfy
the policy.

---

## Why No Issues on Other Lanes

**Scope:** Every item in the bug description is addressed. No gold-plating was introduced —
the enum conversions are the documented secondary fix scope, and `COMMAND_ROLE_MAP` relocation
directly enables the core fix. No unrequested features were added.

**Security:** No secrets, no injection vectors, no sensitive logging, no auth bypass.
`run_slash_command` bypasses the caller-identity check by calling `create_session` directly,
which is the intent of the fix — the daemon is a trusted internal context.

**Paradigm:** The fix follows established patterns. `SlashCommand(str, Enum)` mirrors
`SystemCommand`. `SessionMetadata` frozen dataclass mirrors `ChannelMetadata`. Moving
`COMMAND_ROLE_MAP` to `command_service` follows the principle that shared data belongs to the
module that owns the concept.

**Types:** `SessionMetadata` is a well-designed frozen dataclass with optional fields. The
comparison `s.session_metadata.job == JobRole.INTEGRATOR` is correct because `JobRole` extends
`str`, making `JobRole.INTEGRATOR == "integrator"` true.

**Comments:** Accurate. The `bug.md` fix-applied section matches the diff exactly.

**Demo:** Bug fix — no demo required. Internal daemon behaviour with no CLI surface change.

---

## Verdict: REQUEST CHANGES

Two Important findings remain unresolved:

1. Missing tests for core fix and new `SessionMetadata` serialization paths.
2. Dead code loop in `agent_coordinator._resolve_hook_actor_name` (KISS violation).

The core logic of the fix is correct and the approach is sound. Address the above two items
and re-submit.
