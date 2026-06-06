# Implementation Plan — unified-remote-forwarder

## Scope & atomicity

ATOMIC — single builder session. One coherent behavior: consolidate the
remote-dispatch **sending** side onto one typed primitive plus a
session-ownership resolver, then migrate the two close-forwarding paths onto
the primitive and delete the fake-generic `forward_command`. The pieces are not
independently shippable (the primitive without migration is dead code; the
migration without the primitive is impossible; removing `forward_command`
requires its replacement), so splitting would leave main half-working. Per the
DoR "detail inverts complexity" heuristic, the input pins exact paths, lines,
and mechanisms — discovery is done; this is mechanical execution within one
bounded context (remote session dispatch).

Reference base: this is a `refactor` (plan-only) todo; the `input` artifact is
the upstream contract. Tasks reference it as `@input#<section>`.

## Cross-cutting constraints (apply to every task)

- **Do not change the RECEIVING dispatch contract** (`@input#notes--constraints`).
  `_messaging.py:339-350` (`_dispatch_command` handler table) and
  `_handle_system_message` (`_messaging.py:408`) stay as-is. This work touches
  only the SENDING side plus an ownership lookup.
- **Layer ownership.** The primitive lives in core (`adapter_client/_remote.py`)
  and must raise *domain* errors, never `HTTPException`. The api layer
  (`session_remote.py`) catches those and translates to HTTP status. Core
  decides; the edge translates (project/policy/adapter-boundaries;
  software-development/principle/architectural-defaults §5 layered ownership).
- **Error propagation preserved** (`@input#notes--constraints`): target errors
  surface through the existing envelope path
  (`_messaging.py` `_execute_command` -> `{"status":"error",...}`), and api
  callers keep returning HTTPException 502 (target error) / 503 (transport) /
  504 (timeout), matching `session_remote.py` today.
- **No new trust boundary.** Receiving-side identity gate is unchanged; the
  sending side carries the same identity/origin it does today. DoR security gate
  satisfied by preserving existing receiving auth.
- Not a hot path (session create/close are infrequent). Performance gate
  auto-satisfied.

---

## Task 1 — Add the unified typed remote-dispatch primitive

- [x] Complete Task 1.

Delivers: `@input#goal` (the single forwarder), `@input#notes--constraints`
(error propagation), `@input#problem` items 1-3 (two close senders, inconsistent
sending side).

**What.** Add a typed remote-dispatch method to the `_RemoteMixin` on
`AdapterClient` in `teleclaude/core/adapter_client/_remote.py`. It forwards an
arbitrary command/event *type* (no hardcoding) to a target computer in one of
two modes:
- **request/response-with-payload**: issues `self.send_request(target, command,
  metadata, session_id=...)`, awaits `self.read_response(message_id, timeout,
  target_computer=target)`, parses the envelope, returns the envelope `data`
  payload on `status == "success"`, and raises a domain error on
  `status == "error"`.
- **fire-and-forget**: issues the send and returns `None` without awaiting a
  response.

Envelope parsing mirrors the working pattern in
`teleclaude/transport/redis_transport/_pull.py` (`_parse_envelope` /
`_extract_response_data`) and the error-envelope handling in
`session_remote.py` (`_remote_session_fields` / `_assert_remote_close_success`:
`status == "error"` -> raise). Extract a small shared parse helper rather than
re-implementing, if it reduces duplication without crossing the transport/core
boundary.

Introduce a minimal domain exception (e.g. `RemoteDispatchError`) for the
target-returned-error-envelope case (no such exception exists today — verified).
Let `TimeoutError` and transport `RuntimeError`/`OSError` propagate unwrapped so
api callers map them to 504/503 exactly as `session_remote.py` does now.

Decide the fire-and-forget transport per receiving contract: a command whose
receiver lives in the command handler table (e.g. close ->
`CommandType.CLOSE_SESSION`) must be sent command-typed via `send_request`
(response simply not awaited), NOT via `send_system_command`, so it reaches the
same handler the request/response path uses. `send_system_command` remains
available for genuinely system-typed commands (restart/health_check) that the
receiver routes through `_handle_system_message`.

Log at the dispatch boundary (target computer, command type) using the project
logging framework, matching the existing `logger.warning`/`logger.info` style in
`session_remote.py` and `_pull.py`. No payload secrets in logs.

**Why.** A single parameterized primitive removes the close-only hardcoding in
`forward_command` (`_session.py:40-55`, which ignores `cmd` and hardcodes
`send_system_command(target, "close_session", ...)`) and the duplicated
`send_request`/`read_response` logic in `session_remote.py`. Parameterizing the
command/event type is exactly what lets the downstream consumers
(`remote-session-tail` forwarding `get_session_data`,
`explicit-project-targeting` riding create) reuse it without a new sender each
(`@input#downstream-consumers`).

**Verification.** New unit test (extend
`tests/unit/core/adapter_client/test__remote.py` or a sibling
`test__remote_dispatch.py`, following its existing stub-transport conventions):
- req/resp success envelope -> returns parsed `data`;
- req/resp error envelope -> raises `RemoteDispatchError`;
- req/resp timeout -> `TimeoutError` propagates;
- fire-and-forget -> issues the send (assert the stub received the command-typed
  message at the transport boundary) and returns `None` without reading a
  response.
Run `telec code lint` and `telec code test` on the touched scope.

**Referenced files.** `teleclaude/core/adapter_client/_remote.py`;
`teleclaude/transport/redis_transport/_pull.py` (pattern source, read-only);
`teleclaude/api/session_remote.py` (envelope semantics, read-only);
`tests/unit/core/adapter_client/test__remote.py`.

---

## Task 2 — Add the session-ownership resolver

- [x] Complete Task 2.

Delivers: `@input#goal` (ownership resolver), `@input#problem` item 4
(`db.get_session` is local-only; remote sessions live in the cache).

**What.** Add a resolver that maps a `session_id` to a typed ownership result.
New module `teleclaude/api/session_ownership.py` exposing e.g.
`resolve_session_ownership(session_id, *, db, cache) -> SessionOwnership` where
`SessionOwnership` is a small typed union/dataclass:
- `LocalOwnership(session: Session)` when `db.get_session(session_id)`
  (`teleclaude/core/db/_sessions.py:166`) returns a row;
- `RemoteOwnership(computer: str, snapshot: SessionSnapshot)` when the id is
  absent locally but present in `cache.get_sessions()`
  (`teleclaude/core/cache.py:321`), with the owning computer read from
  `snapshot.computer`;
- a not-found sentinel (`None` / `NotFound`) when neither has it.

Resolution order: local DB first (authoritative for sessions this daemon owns),
then cache (peer-owned). Keep the resolver focused on db-vs-cache ownership; the
tmux ground-truth guard that prevents phantom-peer forwarding stays in the
`_session.py` close handler (Task 3) — do not duplicate it here.

**Why.** `db.get_session` only queries local SQLite, so endpoints that receive a
remote session id silently read empty local state and return 404, or force the
caller to pass a `computer` query param. One resolver derives remoteness from the
id itself and is the single branch point downstream consumers build on
(`@input#downstream-consumers`: `remote-session-tail` branches on this).

**Verification.** New unit test (e.g. `tests/unit/api/test_session_ownership.py`,
following `tests/unit/api/test_session_remote.py` stubbing style): local id ->
`LocalOwnership`; id only in cache with `computer="X"` -> `RemoteOwnership("X")`;
unknown id -> not-found. Use stub db + stub cache. Lint + test on scope.

**Referenced files.** new `teleclaude/api/session_ownership.py`;
`teleclaude/core/db/_sessions.py` (read-only, `get_session`);
`teleclaude/core/cache.py` (read-only, `get_sessions`);
`teleclaude/core/models/_snapshot.py` (read-only, `SessionSnapshot.computer`);
new `tests/unit/api/test_session_ownership.py`.

---

## Task 3 — Migrate the _session.py close-forward; remove forward_command

- [x] Complete Task 3.

Delivers: `@input#goal` (migrate forward_command close path; remove the
fake-generic forwarder), `@input#problem` item 1.

**What.** In `teleclaude/core/command_handlers/_session.py`, replace the
`forward_command(_cmd, target_computer=session.computer_name, client=client)`
call (`~:615`) with a call to the Task 1 primitive, forwarding the close using
the same command/event type the request/response close path uses
(`EVENT_END_SESSION` -> `CommandType.CLOSE_SESSION` receiving contract) with the
session id. Preserve the surrounding locality guard verbatim (the tmux
ground-truth check at `~:600-619` that avoids forwarding a locally-present
session to a phantom peer) and the existing "Forwarding close_session to remote"
info log. Then delete the `forward_command` function (`:40-55`) — verified single
caller.

**Why.** `forward_command` is fake-generic: its signature takes `cmd:
InternalCommand` but the body ignores it and hardcodes a close via
`send_system_command`, routing close through the legacy system-message receiver
instead of the canonical `CLOSE_SESSION` handler. Routing it through the
primitive puts both close paths on one sending mechanism and one receiving
contract without touching the receiving dispatch, and deleting the function
removes the misleading signature that invited misuse.

**Verification.** `grep -rn "forward_command" teleclaude/` returns zero
references after the change. Test (extend the existing close-path coverage,
e.g. `tests/unit/api/test_session_close_remote.py` and/or the `_session`
handler tests): a session the daemon believes remote emits one outgoing close
dispatch with the close type + `target_computer` at the dispatch boundary; a
locally-present session emits no outgoing remote dispatch and keeps the locality
guard intact. Lint + test on scope.

**Referenced files.** `teleclaude/core/command_handlers/_session.py`;
`tests/unit/api/test_session_close_remote.py`.

---

## Task 4 — Migrate session_remote.py close path onto the primitive

- [x] Complete Task 4.

Delivers: `@input#goal` (migrate the session_remote.py close path),
`@input#problem` item 2, `@input#notes--constraints` (error propagation, absorb
the earlier session-close fix while keeping behavior).

**What.** Reimplement `dispatch_session_close_to_peer`
(`teleclaude/api/session_remote.py:199`) to call the Task 1 primitive in
request/response mode (`EVENT_END_SESSION`, `session_id`) instead of inlining
`client.send_request` + `client.read_response` + `_assert_remote_close_success`.
The api function catches the primitive's domain errors and the propagated
timeout/transport errors and maps them to the existing HTTP statuses: target
error envelope -> 502, transport `RuntimeError`/`OSError` -> 503, `TimeoutError`
-> 504. Remove now-dead local helpers (`_assert_remote_close_success`) only if
fully superseded by the primitive's parse; keep the success/error envelope
semantics identical. Leave `dispatch_session_create_to_peer` and
`_remote_session_fields` untouched (create migration is a downstream todo — see
Boundaries).

**Why.** This removes the second competing close sender, collapsing
`dispatch_session_close_to_peer` to a thin api-layer translation (domain error ->
HTTP status) over the shared core primitive, which is the correct layer split.
The earlier session-close fix is absorbed, not reverted: external behavior
(502/503/504, success path) is preserved; only the mechanism is unified.

**Verification.** Extend `tests/unit/api/test_session_remote.py` /
`test_session_close_remote.py`: remote close success -> no error; target error
envelope -> HTTPException status_code 502 without asserting rendered detail text;
transport down -> 503; timeout -> 504. If error prose content is part of the
outward-facing contract, snapshot the full rendered error envelope at that
boundary instead of using literal/substring/pattern assertions. Lint + test on
scope; run the close-path functional/integration test if present.

**Referenced files.** `teleclaude/api/session_remote.py`;
`teleclaude/api/sessions_routes.py` (call site `:612`, read-only — signature
unchanged); `tests/unit/api/test_session_remote.py`;
`tests/unit/api/test_session_close_remote.py`.

---

## Boundaries (explicit non-scope)

- **Create-forward migration is deferred.** `@input#goal` scopes the migration to
  the close paths; create is named only as a downstream enabler
  (`@input#downstream-consumers`, `explicit-project-targeting`). This todo only
  guarantees the Task 1 primitive *supports* the request/response-with-payload
  mode create needs (so `dispatch_session_create_to_peer`'s
  `_remote_session_fields` DTO mapping can later sit on top). Do not refactor the
  create path here.
- **Do not implement the downstream consumers** (`remote-session-tail`,
  `explicit-project-targeting`) — only enable them via the primitive + resolver
  (`@input#downstream-consumers`).
- **Do not touch the receiving dispatch** (`_messaging.py` handler table and
  `_handle_system_message`).

## Definition of Done close-out

After Task 4: run `telec code lint` and `telec code test` across the full
touched scope; confirm `grep -rn "forward_command" teleclaude/` is empty; confirm
no remote close/create behavior regressed (regression-zero-tolerance — the
502/503/504 envelope mapping and the locality guard are pinned by tests). All new
behavior (primitive, resolver) is bound by the unit tests named above; the two
migrated close paths keep their existing test bindings, re-pointed through the
primitive.

---

## Task 5 — Address carried-over review findings (from the absorbed session-close fix)

- [x] Complete Task 5.

A cross-model review of the original session-close commits (c776a78ae, 46f599028,
f62ce0992) returned REQUEST CHANGES. This todo reworks that exact code, so the three
still-valid findings are REQUIREMENTS, implemented as part of the close-path migration
(Tasks 3-4) and its tests. (The other two findings are moot: the non-atomic split commit
is already-merged history — just keep each commit here standalone-importable; the
substring-assertion test was already removed for violating the spec-anchored testing policy.)

**5a — Remote-close authorization ordering (functional).** In `teleclaude/api/sessions_routes.py`
`end_session`, the local-only `check_session_access(require_owner=True)` currently runs BEFORE
the remote branch, so a web-identity caller who can see a peer-owned session in the merged cache
is rejected with a local "Session not found" before the close is ever forwarded. Use the
session-ownership resolver introduced in Task 2: when the target is remote, authorize against the
remote/cached ownership (or forward an authorization-aware close) instead of the local DB-only
access check. Web-ownership semantics still apply per the identity trust-boundary model; the fix is
ordering + using the resolver, not bypassing auth.

**5b — Remote close must honor the `completion_event` contract.** The documented end-session
response contract (docs/project/spec/feature/agent_runtime/session-lifecycle.md) exposes a
`completion_event` on accepted closes. The unified request/response close path must return the
completion event for remote closes too — or, if remote close intentionally differs, update the spec
and every consumer. Do not silently drop it.

**5c — API-boundary test.** Add a functional boundary test for `DELETE /sessions/{id}?computer=<peer>`
proving the route forwards to the owning computer and does NOT fall through to a local close — a test
that would FAIL if the route ignored `computer`. (The prior tests only exercised the helper, so they
passed even when the route was wrong.) Author per the spec-anchored testing policy (functional level),
not as an orphaned unit test.
