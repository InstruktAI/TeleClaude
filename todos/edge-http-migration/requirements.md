# edge-http-migration — Requirements

## Problem Statement

Three daemon-internal session-spawning flows bypass the API edge layer to
create sessions: the integration bridge, the prepare cartridge, and WhatsApp
hook handling. This violates the layer-ownership architecture because
edge-owned origin context is never assembled, and identity resolution is
skipped.

## Requirements

### R1: All session creation flows through the API edge

Every daemon-internal caller that currently creates sessions by invoking core
session-creation services directly must instead issue HTTP requests to the
existing public API session creation endpoints (`POST /sessions` or
`POST /sessions/run`).

**Success criteria:**

- No production code path creates sessions by calling core session-creation
  services directly from outside the API route handlers.
- The edge layer assembles the request's origin and identity payload for every
  session creation request, including daemon-internal ones.
- Identity resolution executes for every session creation, consistent with the
  layer-ownership architecture's "Human via origin" traversal flow.

**Affected callers:**

- The integration bridge session-spawning path.
- The prepare cartridge worker-dispatch path.
- The WhatsApp handler session-creation path.

### R2: Daemon self-authentication for internal API calls

The daemon must authenticate when calling its own API endpoints for
daemon-internal session creation. The input specifies that the daemon
authenticates with its session token.

**Success criteria:**

- Daemon-internal HTTP calls to the session creation endpoints authenticate
  successfully through the existing auth middleware. [inferred]
- The auth identity resolved for daemon-internal calls carries appropriate
  role information so that existing clearance checks pass. [inferred]
- No auth bypass or special-case logic is introduced that weakens the
  security boundary. [inferred]

### R3: Remove `run_slash_command` from `CommandService`

Once all callers are migrated to HTTP, `CommandService.run_slash_command`
becomes dead code and must be removed.

**Success criteria:**

- The `run_slash_command` method no longer exists on `CommandService`.
- No production code references `run_slash_command`.
- The `COMMAND_ROLE_MAP` constant remains available if the API route handlers
  still reference it. [inferred]

### R5: Behavioral preservation

All existing session creation behavior must be preserved through the
migration. [inferred]

**Success criteria:**

- Integration bridge sessions launch with the correct system_role
  (`integrator`), job (`integrator`), and `detach=True` behavior.
- Prepare cartridge sessions launch with the correct system_role (`worker`),
  job (`prepare_orchestrator`), slug argument, and `detach=True` behavior.
- WhatsApp sessions are found-or-created by phone number, carry the correct
  origin and origin_metadata, and the adapter dispatch path continues to
  function for message routing to existing sessions.
- Session token issuance, tmux launch, and listener registration behavior
  remain unchanged.
- Existing tests that validate these paths are updated to reflect the new
  call pattern (HTTP via edge) rather than the old one (direct service call).

### R6: `COMMAND_ROLE_MAP` remains the single source of truth for role assignment

The `COMMAND_ROLE_MAP` that maps slash commands to `(system_role, job)` pairs
is currently consumed by both `run_slash_command` and the API route handler
for `POST /sessions/run`. After `run_slash_command` is removed, the map must
continue to serve as the authoritative source for the API route. [inferred]

**Success criteria:**

- `COMMAND_ROLE_MAP` remains defined and used by the `POST /sessions/run`
  route handler for deriving system_role and job from slash commands.
- No duplication of role-mapping logic is introduced.

## Deferred / Out of scope

- **`channel_metadata` to `origin_metadata` rename** — covered by dependent
  todo `origin-metadata-rename`.
- **Outbound adapter dispatch** (`_dispatch_whatsapp_command` routing messages
  to existing sessions via the adapter) is not part of this change.
- **Remote session creation** (creating sessions on remote computers via the
  API) is not in scope.

## Verification strategy

- Pre-commit hooks (lint, typecheck, tests) must pass.
- Tests for the integration bridge, prepare cartridge, and WhatsApp session
  creation paths verify that they call the public session endpoints with the
  correct request bodies and caller authentication, rather than invoking core
  session-creation services directly.
- Auth-focused tests verify that session-token-authenticated internal calls
  resolve a caller identity that passes the existing clearance checks.
  [inferred]
- Search-based verification confirms that no production code references
  `run_slash_command` and that `POST /sessions/run` continues to use
  `COMMAND_ROLE_MAP` as its role-assignment source. [inferred]
- Behavioral preservation is verified through targeted tests covering
  integrator spawning, prepare worker dispatch, WhatsApp session lookup and
  creation, and unchanged session bootstrap side effects such as session token
  issuance, tmux launch, and listener registration. [inferred]
