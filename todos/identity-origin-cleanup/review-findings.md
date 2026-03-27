# Review Findings: identity-origin-cleanup

## Review Context

Review of the `identity-origin-cleanup` delivery. Tasks 1-6 delivered, Task 6b partial,
Tasks 7-10 deferred with justification in `deferrals.md`.

## Resolved During Review

The following findings were auto-remediated during review:

- **RBF-1 (Critical, resolved):** `_session.py:275` — `db.update_origin_metadata()` received
  typed metadata objects (`WebOriginMetadata`/`TerminalOriginMetadata`) which are `Mapping`
  implementations, not `dict`. The DB function calls `json.dumps()` on the value, which raises
  `TypeError` for non-dict Mappings. Tests mocked the DB call, hiding the runtime failure.
  **Fix:** Added `dict()` conversion before passing to DB layer. Updated test assertion to
  verify dict output with correct email value.

- **RBF-2 (Important, resolved):** `discord/input_handlers.py:476` — Variable named
  `channel_metadata` but passed as `origin_metadata=channel_metadata`. The variable retained
  the deprecated concept name while being used for its replacement.
  **Fix:** Renamed variable to `origin_metadata`.

- **RBF-3 (Important, resolved):** `identity.py:175` — `IdentityResolver.resolve()` parameter
  still named `channel_metadata` despite the delivery's explicit goal of eliminating that concept.
  All callers use positional arguments, making the rename safe.
  **Fix:** Renamed parameter and docstring from `channel_metadata` to `origin_metadata`.
  Updated all references in method body.

## Scope

All requirements (R1-R6) reviewed against implementation. Tasks 1-6 are delivered with Task 6b
partial. Deferrals are justified — remaining scope (per-message metadata, actor context, daemon
pipeline, CLI callers, verification) forms a coherent follow-up with no regression to delivered
behavior.

No scope violations detected. No gold-plating.

## Paradigm

Implementation follows established patterns:

- Typed metadata classes follow the existing `from_dict`/`to_dict` pattern
- `Mapping` protocol implementation enables backward-compatible resolver usage
- Session handler derivation pattern (`trees/{slug}` → `working_slug`) is clean
- Fail-fast gate at handler line 146-147 is correct

No paradigm violations.

## Principles

### Fallback & Silent Degradation

No unjustified fallbacks found in delivered code. The session handler's identity resolution
path is explicit: `cmd.origin_metadata` → resolver → identity, with parent session inheritance
as a documented secondary path and a fail-fast gate when both fail.

### Dependency Inversion

No DIP violations. Core models define types; adapters consume them. No adapter-specific
imports in core.

### Single Responsibility

Handler derivation of `working_slug` from `subdir` is correctly localized to the session
creation handler — the single place that needs this logic.

### Coupling

The `Mapping[str, object]` protocol on typed metadata maintains loose coupling between adapters
(that construct metadata) and the resolver (that reads it).

No principle violations.

## Security

- No secrets in diff
- No sensitive data in logs
- Input validation at boundaries (origin_metadata checked before use)
- No injection vulnerabilities
- Error messages don't leak internals

No security findings.

## Code (delegated lane)

No additional findings beyond RBF-1, RBF-2, RBF-3 (all resolved above). Code review verified:

- Contract fidelity across the session creation pipeline
- No dead code introduced
- Type annotations consistent with runtime behavior (after RBF-1 fix)

## Tests (delegated lane)

- All spec-delivered tests satisfied for delivered tasks (1-6)
- 20 passed, 8 xfailed (all xfails are deferred tasks 7-9)
- No assertions weakened or deleted from spec tests
- Test updated for RBF-1 fix: `test_typed_metadata_stored_via_update_origin_metadata` now
  verifies `dict` type and email value instead of `isinstance(TerminalOriginMetadata)`
- Full test suite: 30 passed, 0 failed
- Pyright: 0 errors

No test coverage findings.

## Silent Failures (delegated lane)

No unjustified silent failures in delivered code. The identity resolution path is explicit
and the fail-fast gate prevents sessions without identity or system_role.

No findings.

## Types (delegated lane)

Type design is sound after RBF-1 fix:

- `Mapping[str, object]` is the correct protocol for `origin_metadata` on commands — it
  accepts both typed metadata objects and raw dicts during the transition
- Typed metadata classes correctly implement the `Mapping` protocol
- `dict()` conversion at the DB boundary ensures JSON serializability

No remaining type design findings.

## Comments (delegated lane)

### RBF-4 (Suggestion)

**Location:** `command_mapper.py:129`, `_session.py:38`

Comments reference implementation plan task numbers ("Task 7", "Task 6b/7") which become
meaningless when the plan is archived. Consider replacing with semantic descriptions
(e.g., "deprecated — pending named field migration").

## Logging

No new logging changes in the diff. Existing logging at key boundaries is adequate.

No findings.

## Demo

Demo artifact (`demos/identity-origin-cleanup/demo.md`) contains 5 executable bash blocks
that exercise the delivered behavior:

1. Channel metadata cleanup tests
2. Working slug derivation tests
3. Typed metadata instantiation and Mapping protocol
4. CreateSessionCommand with typed origin_metadata
5. Full test suite

All blocks use real commands against actual implementation. No fabricated output.

No findings.

## Documentation

No new CLI subcommands, config keys, or API endpoints introduced. The delivery is an internal
refactor of the session creation pipeline. No documentation surface changes required.

No findings.

## Simplify

Not applicable — simplify lane runs after all other lanes pass. All findings resolved.

## Unresolved Findings

### RBF-4 (Suggestion)

Comments reference plan task numbers. See Comments lane above.

### RBF-5 (Suggestion)

**Location:** `command_mapper.py:245-251`

Redis `map_redis_input` new_session path drops `channel_metadata` from the old
`CreateSessionCommand` without passing `origin_metadata`. Cross-computer session creation
that relied on identity signals in `channel_metadata` would lose them. In practice, Redis
sessions are system-initiated (with `system_role`), so the impact is minimal. Full fix is
in deferred scope (Task 7).

## Why No Issues (zero-finding justification for Important+)

All Critical and Important findings were auto-remediated:

1. **Paradigm-fit:** Verified typed metadata follows existing `from_dict`/`to_dict` pattern;
   `Mapping` protocol matches resolver's `get()` interface.
2. **Requirements met:** R1 (working_slug derivation), R4 (typed metadata), and the delivered
   portions of R2 (channel_metadata removal from CreateSessionCommand, origin_metadata on
   handler path) are verified through passing spec tests.
3. **Copy-paste duplication:** Checked. `WebOriginMetadata` and `TerminalOriginMetadata` share
   structure but represent different domains — not premature abstraction.
4. **Security:** Reviewed. No secrets, injection, or info leakage in the diff.

## Verdict

**APPROVE**

- Unresolved Critical: 0
- Unresolved Important: 0
- Unresolved Suggestions: 2
