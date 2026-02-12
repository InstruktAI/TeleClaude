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

- Hook receiver resolves session identity from native mapping (`agent:native_session_id`) plus DB native lookup.
- Receiver does not use per-session TMP marker files for hook routing.
- New mapping registration happens only on `session_start`.
- Non-`session_start` events without an existing mapping are dropped.

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
- `drop-unmapped-non-session-start`

## Known caveats

- Legacy marker-based routing is intentionally removed from hook identity resolution.
- Native fields may be missing in some events; logic must handle that safely.
- This file is only useful if kept in sync with receiver + mapping code behavior.
