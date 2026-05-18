---
description: 'Practical identity rules for assigning hooks to the correct TeleClaude session.'
id: 'project/spec/session-identity-truth'
scope: 'project'
type: 'spec'
visibility: 'public'
---

# Session Identity Truth — Spec

## What it is

This file exists to prevent one expensive class of bug:

"Hook/event got attached to the wrong session."

It explains, in plain terms, how session identity is resolved for:

- managed TeleClaude sessions,
- headless/standalone hook sources.

Use it when:

- you debug wrong-session attribution,
- you touch session mapping logic,
- headless behavior looks fragmented.

## Canonical fields

This spec must define:

- managed route behavior,
- headless route behavior,
- which identity source wins per route,
- where native-to-teleclaude mapping is stored,
- what happens when identifiers disagree,
- restart/recovery behavior.

Current runtime rule:

- Non-headless (TMUX) route:
  - session id comes directly from `TMPDIR/teleclaude_session_id`.
  - no map/DB lookup on this route.
  - missing/empty marker is a contract violation.
- Headless route:
  - resolve via native mapping (`agent:native_session_id`) then DB native lookup.
  - new mapping registration happens at explicit adoption points:
    - `session_start` (all agents),
    - `agent_stop` (Codex only).
  - if a handled event cannot resolve a session id, it is a contract violation.

Fields that must be explained:

- TeleClaude session id,
- native session id (if present),
- native transcript/log path (if present),
- mapping record location/reference.
- distinction between request-time typed metadata and `origin_metadata`, and how each is used.

### Origin Data Model

Two related but distinct concepts carry origin information:

- **Request-time typed metadata**: the edge normalizes raw platform signals into typed fields before the command enters core. Message flows use `MessageMetadata.actor_id`, `actor_name`, `actor_avatar_url`, and `platform_message_id`. Session-creation flows use typed origin metadata objects such as `TerminalOriginMetadata` or `WebOriginMetadata`. Identity resolution consumes these typed inputs at request time.
- **`origin_metadata`**: per-session JSON column on the sessions table. It is the accumulated merge of session origin sections received during the session's lifetime. Persisted via `update_origin_metadata` (merge-on-write). Carries the `platform` key (last input origin) plus all platform sections.

Identity resolution reads from the typed metadata presented on the active command. Long-term identity derivation (e.g. `derive_identity_key`) reads from `origin_metadata`.

## Allowed values

Route type:

- `managed`
- `headless`

Authority mode:

- `native-mapping-authoritative`

Recovery outcome:

- `reassociate-existing`
- `mint-new`
- `tmux-contract-violation`
- `identity-contract-violation`

## Known caveats

- TMUX route trusts marker content by contract; it does not validate DB session existence.
- Native fields may be missing in some events; logic must handle that safely.
- This file is only useful if kept in sync with receiver + mapping code behavior.

**Identity representation invariant:** The full UUID must be used in every context where a
session ID appears — log fields, structured log kwargs, message bodies, notification text,
error strings, exception messages, and API response bodies. Truncation (`[:8]`, `[:12]`, or
any other slice) is never permitted on session, operation, or native IDs. The only permitted
exception: tmux session name labels (`tc_{session_id[:8]}`), which are UI display identifiers
and are never used as API keys or lookup values. Reviewers must reject any diff that introduces
`[:8]` or similar truncation on an identifier variable.
