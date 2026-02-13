---
id: 'project/spec/session-identity-truth'
type: 'spec'
scope: 'project'
description: 'Practical identity rules for assigning hooks to the correct TeleClaude session.'
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
