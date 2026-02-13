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

- Hook receiver resolves session identity in this order:
  1. native mapping (`agent:native_session_id`)
  2. DB lookup by `native_session_id`
  3. TMPDIR `teleclaude_session_id` marker when active
- New mapping registration happens only on `session_start`.
- If no route resolves a session id, the event is dropped.

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
- `drop-unresolved`

## Known caveats

- TMPDIR marker routing is fallback-only and ignored when the marker target is not active.
- Native fields may be missing in some events; logic must handle that safely.
- This file is only useful if kept in sync with receiver + mapping code behavior.
