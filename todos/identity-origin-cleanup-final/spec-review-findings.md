# Test Spec Review Findings — identity-origin-cleanup-final

Reviewed: 2026-03-28

## Verdict: needs_work

---

## Coverage Map

### R1 — Typed actor fields on MessageMetadata

**Status: COVERED — but wrong fields tested, contradicts R9**

Location: `tests/unit/transport/redis_transport/test_target_computer_named_field.py::TestActorContextNamedFields`

**Finding F1 [Critical]** — Spec tests dead data fields that R9 explicitly forbids.
`test_message_metadata_has_actor_fields` constructs `MessageMetadata` with `actor_role`,
`actor_agent`, `actor_computer`. R9 states these keys are dead data and "must not be carried
forward to the typed fields." The spec is directly at odds with the requirements: if the builder
passes R1 by adding these fields to `MessageMetadata`, they will fail R9. If they pass R9 by
omitting them, this test fails. The contradiction must be resolved before implementation.

**Finding F2 [Critical]** — Spec misses required fields from R1.
R1 specifies `actor_id`, `actor_name`, `actor_avatar_url`, `platform_message_id`. The spec
only tests `actor_id` and `actor_name`. `actor_avatar_url` and `platform_message_id` are
entirely absent from the xfail spec. A builder could satisfy the spec while omitting these fields.

**Required fix:** Update `TestActorContextNamedFields.test_message_metadata_has_actor_fields`
to test exactly the fields named in R1 (`actor_id`, `actor_name`, `actor_avatar_url`,
`platform_message_id`), removing `actor_role`, `actor_agent`, `actor_computer`.

---

### R2 — Adapter-edge normalization

**Status: MISSING — no xfail spec**

No xfail spec tests that adapters (Telegram, Discord, WhatsApp, fanout) set typed actor fields
directly on `MessageMetadata` instead of populating a dict. The platform-specific ID prefixing
contract (`telegram:{id}`, `discord:{id}`) has no spec coverage at all.

**Finding F3 [Critical]** — No spec for Telegram adapter actor normalization.
After R2, `_metadata()` in `InputHandlersMixin` must set `actor_id`, `actor_name`, etc. directly
on `MessageMetadata`. The existing characterization test at
`tests/unit/adapters/telegram/test_input_handlers.py:31` still uses
`MessageMetadata(channel_metadata=dict(kwargs))` — this pins the old behavior but no xfail
spec defines the new behavior the builder must deliver.

**Finding F4 [Critical]** — No spec for Discord adapter actor normalization.
After R2, the Discord gateway handler must set typed fields. No xfail spec verifies this.

**Finding F5 [Critical]** — No spec for platform ID prefix convention.
R2 states the `telegram:{id}` / `discord:{id}` prefixing must happen at the adapter edge. This
is a behavioral contract that will determine how actor identity is resolved downstream. No test
spec captures it. A builder could implement R2 without the prefixing, or with the wrong prefix
format, and no test would catch it.

**Required fix:** Add xfail specs in the relevant adapter test files or a new
`test_adapter_actor_normalization.py` for:

- Telegram sets `actor_id = f"telegram:{user_id}"`, `actor_name`, `platform_message_id` on `MessageMetadata`
- Discord sets `actor_id = f"discord:{user_id}"`, `actor_name` on `MessageMetadata`
- (WhatsApp is partially covered in existing non-xfail tests but the `channel_metadata`
  migration path also needs spec coverage)

---

### R3 — Eliminate centralized actor extraction

**Status: PARTIALLY COVERED — one weak test**

`TestActorContextNamedFields.test_fanout_does_not_construct_channel_metadata_dict` uses AST
inspection to verify the fanout does not use `channel_metadata` as a keyword argument.

**Finding F6 [Important]** — AST-based test is implementation-coupled and fragile.
The test walks the AST looking for `keyword.arg == "channel_metadata"`. This would pass if the
fanout uses a different approach that still bypasses typed fields (e.g., `**{"channel_metadata": ...}`).
More importantly, it does not verify that actor data actually flows correctly through typed fields — it
only checks that a dict key name is absent. A behavioral test (e.g., running the fanout and asserting
`MessageMetadata.actor_id` is set on output) would be stronger.

**No spec for CommandMapper reading typed fields.** After R3, `CommandMapper.map_*_input` methods
must read `actor_id`, `actor_name`, `actor_avatar_url`, `platform_message_id` directly from
`MessageMetadata` fields. No xfail spec verifies this. The existing characterization tests in
`test_command_mapper.py` do not set these fields and do not assert they flow into commands.

---

### R4 — Redis wire format migration

**Status: MISSING — no xfail spec**

The Redis wire format migration has zero xfail spec coverage. The existing characterization tests in
`tests/unit/transport/redis_transport/test__messaging.py` actively pin the old `channel_metadata`
JSON blob wire format (lines 47–61). These tests will need to be deleted or rewritten after R4, but
there is no spec defining what the new behavior should look like.

**Finding F7 [Critical]** — No spec for typed Redis wire format deserialization.
After R4, `_parse_redis_message` must deserialize `actor_id`, `actor_name`, `actor_avatar_url`,
`platform_message_id` as individual fields from the wire. No xfail spec captures this contract.
The builder has no spec-defined target for what a correct Redis message parse looks like after R4.

**Finding F8 [Critical]** — No spec for `RedisTransportMetadata` dropping `channel_metadata`.
R4 requires `RedisTransportMetadata` to drop its `channel_metadata` field. No xfail spec verifies
the field is absent. The existing test at `test__adapter.py:321–335` characterizes
`channel_metadata` still being present — it will break after R4, but the spec doesn't define
the new model shape.

**Required fix:** Add xfail specs covering:

- `RedisInboundMessage` has `actor_id`, `actor_name`, `actor_avatar_url`, `platform_message_id`
  fields and no `channel_metadata`
- `_parse_redis_message` reads each actor field individually from the wire
- `RedisTransportMetadata` does not have a `channel_metadata` field

---

### R5 — Dead code removal in Redis transport

**Status: PARTIALLY COVERED**

`TestTargetComputerNamedField.test_handle_incoming_message_does_not_inject_target_computer_into_dict`
and `test_redis_mapper_does_not_produce_channel_metadata` cover the absence of `channel_metadata`
on `CreateSessionCommand`. These are in the correct direction, though they are not marked xfail
at the class level — only `TestActorContextNamedFields` has a class-level xfail. The
`TestTargetComputerNamedField` tests will run as normal tests and may currently fail if
`channel_metadata` still exists on commands.

**Finding F9 [Minor]** — `TestTargetComputerNamedField` tests lack xfail markers.
The file docstring says "Remove `pytestmark = pytest.mark.xfail` once all tests pass" but
`TestTargetComputerNamedField` has no module-level or class-level `pytestmark`. The tests
will run eagerly (not as expected failures). If `channel_metadata` currently exists on
`CreateSessionCommand`, these will fail as hard failures rather than xfail.

---

### R6 — Headless session creation via command pipeline

**Status: WELL COVERED**

`TestDaemonHeadlessViaCommandPipeline` in `tests/unit/test_daemon_headless_pipeline.py`:

- `test_ensure_headless_session_does_not_call_db_directly` — patches `db.create_headless_session` and asserts it was not called. A broken implementation would fail.
- `test_headless_session_does_not_call_resolve_from_terminal` — tracks via closure flag. Solid.

Both tests are module-level xfail. Coverage is adequate.

---

### R7 — Remove `resolve_from_terminal()`

**Status: WELL COVERED**

- `TestResolveFromTerminalRemoved.test_identity_resolver_has_no_resolve_from_terminal` — `hasattr` check on the class. Will fail if the method exists.
- `TestCliCallersAlternativePath` — three tests (docs, config_cli, cartridge_cli) each inject a mock resolver that lacks `resolve_from_terminal`. If the callers still call `resolve_from_terminal`, `AttributeError` is raised and xfail catches it. When callers switch to `resolve()`, the test passes with the mock.

Coverage is adequate. The `_cartridge_cli` test additionally asserts `isinstance(result, bool)` — this catches the case where the function returns None instead of a bool.

---

### R8 — Documentation updates

No test specs. Acceptable — documentation changes are verified by the success criteria grep commands in requirements.md, not by automated tests.

---

### R9 — Dead data removal in fanout

**Status: CONTRADICTED by R1 spec (see F1)**

R9 states `actor_role`, `actor_agent`, `actor_computer` in `channel_metadata` are dead data and must NOT be carried forward. The xfail spec for R1 (`TestActorContextNamedFields.test_message_metadata_has_actor_fields`) directly tests these as named fields on `MessageMetadata`, which contradicts R9. This is the same issue as F1 — one finding, two requirements violated.

---

### Out-of-scope spec: `test_typed_origin_metadata.py`

**Finding F10 [Important]** — Spec tests functionality not in requirements.
`tests/unit/core/models/test_typed_origin_metadata.py` is labeled "Test spec (xfail) for R4" but
R4 in the requirements is Redis wire format migration. This file tests `WebOriginMetadata` and
`TerminalOriginMetadata` typed dataclasses — neither of these appears anywhere in the requirements.

Options:

- If these types are an implied sub-task of R7 (CLI callers need typed metadata to call `resolve()`
  instead of `resolve_from_terminal()`), the spec should be labeled as such and the requirements
  updated to make this explicit.
- If they are genuinely out of scope, the spec file should be removed to avoid confusing the builder.

The mislabeling as "R4" is itself a defect — a builder reading the spec would assume R4 = typed
origin metadata, contradicting the requirements definition of R4.

---

## Findings Summary

| ID  | Severity  | Description                                                                                                            |
| --- | --------- | ---------------------------------------------------------------------------------------------------------------------- |
| F1  | Critical  | R1 spec contradicts R9: tests `actor_role`, `actor_agent`, `actor_computer` (dead data) on `MessageMetadata`           |
| F2  | Critical  | R1 spec misses `actor_avatar_url` and `platform_message_id`                                                            |
| F3  | Critical  | No xfail spec for Telegram adapter-edge normalization (R2)                                                             |
| F4  | Critical  | No xfail spec for Discord adapter-edge normalization (R2)                                                              |
| F5  | Critical  | No xfail spec for platform ID prefix convention (`telegram:{id}`, `discord:{id}`) (R2)                                 |
| F7  | Critical  | No xfail spec for typed Redis wire format deserialization (R4)                                                         |
| F8  | Critical  | No xfail spec for `RedisTransportMetadata` dropping `channel_metadata` (R4)                                            |
| F6  | Important | R3 fanout spec is AST-based (implementation-coupled), not behavioral                                                   |
| F10 | Important | `test_typed_origin_metadata.py` tests out-of-scope types (WebOriginMetadata, TerminalOriginMetadata); mislabeled as R4 |
| F9  | Minor     | `TestTargetComputerNamedField` lacks xfail markers — tests run eagerly and may produce hard failures                   |

**Critical count: 7 | Important count: 2 | Minor count: 1**
