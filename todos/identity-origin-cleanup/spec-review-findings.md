# Test Spec Review Findings: identity-origin-cleanup

## Summary

**Verdict: needs_work**

The spec suite (32 tests: 16 xfailed, 8 xpassed, 8 skipped) delivers real behavioral coverage for
R1, R2, and R6. Two critical gaps prevent approval: R3 has no test that exercises the actual
injection code path in `_messaging.py`, and the R4 resolver tests assert pre-existing dict
behavior instead of the new typed metadata contract. Several important weaknesses weaken
otherwise-sound specs.

---

## Findings

### TSR-1 — R3: No test exercises the actual `target_computer` injection path (Critical)

**File:** `tests/unit/transport/redis_transport/test_target_computer_named_field.py`

**What:** The code that must change for R3 is `teleclaude/transport/redis_transport/_messaging.py`
lines 248–250:

```python
# Ensure target_computer set for stop forwarding
metadata.channel_metadata = metadata.channel_metadata or {}
metadata.channel_metadata["target_computer"] = parsed.initiator
```

None of the three R3 tests exercise this path:

- `test_redis_transport_metadata_has_target_computer_field` — asserts `RedisTransportMetadata`
  already has a `target_computer` field. This is pre-existing behavior; the test xpasses
  immediately and cannot become "newly green" when R3 is implemented.
- `test_incoming_message_does_not_inject_target_computer_into_channel_metadata` — constructs a
  bare `MessageMetadata(channel_metadata={"user_id": 12345})` and checks `target_computer not in`
  it. Trivially true: the test itself provides the clean metadata; the injection code is never
  invoked.
- `test_redis_mapper_new_session_preserves_clean_channel_metadata` — exercises
  `CommandMapper.map_redis_input`, which does not perform the injection. The injection happens
  upstream in `_handle_incoming_message`.

**Impact:** The builder has no failing spec test that targets the actual regression site. R3 can
be considered "done" by the builder after implementing `RedisTransportMetadata` changes without
ever touching the `channel_metadata` injection on line 250. The critical behavior — that
`target_computer` no longer lands in `channel_metadata` — is unguarded.

**Required:** Add a spec test that exercises `_handle_incoming_message` (or the equivalent path
that parses incoming Redis messages) with `initiator` set, and asserts that `target_computer`
appears on the named metadata field rather than in `channel_metadata`.

---

### TSR-2 — R4: Resolver tests assert pre-existing dict behavior, not typed metadata contract (Critical)

**File:** `tests/unit/core/models/test_typed_origin_metadata.py`,
`TestIdentityResolverReadsTypedMetadata`

**What:** Both `test_resolver_resolves_identity_from_web_origin_metadata` and
`test_resolver_resolves_identity_from_terminal_origin_metadata` call `resolver.resolve("web", {"email": ...})` — passing a raw `dict`, not a `WebOriginMetadata` or `TerminalOriginMetadata`
instance. The `IdentityResolver.resolve()` method already accepts `Mapping[str, object]` and
reads `email` from it. These tests exercise pre-existing behavior; they will xpass before any R4
implementation is written.

The requirement states: _"The identity resolver can read from these typed schemas when resolving
identity from `origin_metadata`."_ The behavioral contract is that the resolver works with
typed instances — either by accepting them directly or by converting them to dict via `to_dict`.
The current tests do not capture this contract.

**Impact:** A builder can deliver R4's typed classes without wiring them into the resolver path
and these tests will still pass. The coupling between the new types and the resolver is unguarded.

**Required:** Replace or augment with a test that passes a `WebOriginMetadata(email=...)` instance
(not a raw dict) to `resolver.resolve()` and asserts the resolver produces the correct identity.
This test will xfail before R4 wires the typed schemas; it becomes green when the wiring is done.

---

### TSR-3 — Optional-guard anti-patterns allow assertion-free passes (Important)

**Files:**

- `test_channel_metadata_cleanup.py` → `TestChannelMetadataEdgeOnly::test_channel_metadata_stored_unchanged_from_edge` (line 285: `if db.update_origin_metadata.called:`)
- `test_target_computer_named_field.py` → `test_redis_mapper_new_session_preserves_clean_channel_metadata` (line 64: `if create_cmd.channel_metadata:`)
- `test_channel_metadata_cleanup.py` → `TestCommandMapperNoInternalFieldInjection::test_channel_metadata_passthrough_preserves_edge_signals_only` (line 224: `if create_cmd.channel_metadata:`)

**What:** Each of these tests gates its assertions behind an `if` block. A trivially wrong
implementation (e.g., `update_origin_metadata` never called, `channel_metadata` returned as
`None`) satisfies these specs with zero assertions executed. Per the testing policy: "Truthy-check
assertions — `assert value` passes for any non-empty value. If a trivially wrong implementation
satisfies the assertion, the assertion is worthless."

**Required:** Replace `if ... called:` / `if create_cmd.channel_metadata:` guards with
unconditional assertions. For `update_origin_metadata`, assert it was called and assert on the
stored value. For `channel_metadata`, assert it is not None before checking its contents.

---

### TSR-4 — R6 CLI caller tests use source inspection, not behavioral contracts (Important)

**File:** `tests/unit/test_daemon_headless_pipeline.py`, `TestCliCallersAlternativePath`

**What:** All three CLI caller tests use `inspect.getsource(module)` and assert that
`"resolve_from_terminal"` is absent from the source text. This is a source-code text assertion
(implementation-coupled), not a behavioral contract. It breaks if the string appears in a comment
or import alias, and it does not verify that the CLI callers actually _work_ after the method is
removed.

The requirement says CLI callers must _"use an alternative path that does not depend on a method
being removed."_ The spec should verify that alternative path functions — e.g., that
`docs_handler.resolve_identity()` (or equivalent) returns a valid identity without calling the
removed method.

**Required:** Replace source inspection with behavioral tests: import the module's resolution
entry point, call it with a mocked config/people list, and assert it returns a valid identity
context. These tests will xfail when `resolve_from_terminal` is the only path, and go green when
the alternative path is wired up.

---

### TSR-5 — Exception swallowing in R6 pipeline tests (Important)

**File:** `tests/unit/test_daemon_headless_pipeline.py`,
`TestDaemonHeadlessViaCommandPipeline`

**What:** Both tests use bare `try/except: pass` around the call to `_ensure_headless_session`.
If the method raises _before_ reaching `db.create_headless_session` or `get_identity_resolver()`
(e.g., due to a missing mock or import error), the exception is silently swallowed and the
assertion trivially passes.

For example, in `test_ensure_headless_session_does_not_call_db_directly`, if
`_ensure_headless_session` raises `AttributeError` on the first line, `mock_db.create_headless_session`
is never called, and `assert not mock_db.create_headless_session.called` passes — but the
behavior wasn't actually tested.

**Required:** Narrow the exception handling to expected exceptions (e.g., `NotImplementedError`
from `_queue_background_task`), and let unexpected exceptions propagate. Alternatively, assert
that the method completes a meaningful portion of its work (e.g., reaches a checkpoint) before
checking the negative assertion.

---

### TSR-6 — R1: Missing caller-site coverage for callers that currently set `working_slug` (Suggestion)

**What:** The specs test that `CreateSessionCommand` loses the `working_slug` field and that the
command mapper doesn't extract it. But the grounded paths include
`teleclaude/api/sessions_actions_routes.py` and `teleclaude/core/agent_coordinator/_fanout.py`,
which may currently set `working_slug` on the command at construction time. If these callers
pass `working_slug=...` as a constructor kwarg, they will break after R1 removes the field —
and there are no specs to guard this regression path.

**Suggested:** Add xfail specs asserting that the API routes and fanout coordinator construct
`CreateSessionCommand` without `working_slug`. These tests would xfail before R1 cleans up
the callers and go green once callers are updated.

---

## Required coverage before approval

| Finding | Requirement | Action                                                                |
| ------- | ----------- | --------------------------------------------------------------------- |
| TSR-1   | R3          | Add spec testing `_handle_incoming_message` injection path            |
| TSR-2   | R4          | Replace/augment resolver tests to pass typed instances, not raw dicts |
| TSR-3   | R2/R3/R5    | Remove optional-guard anti-patterns; make assertions unconditional    |
| TSR-4   | R6          | Replace source inspection with behavioral identity-resolution tests   |
| TSR-5   | R6          | Narrow exception handling; prevent assertion-free passes              |
