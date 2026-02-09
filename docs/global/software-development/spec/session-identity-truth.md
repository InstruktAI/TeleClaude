---
id: 'software-development/spec/session-identity-truth'
type: 'spec'
domain: 'software-development'
scope: 'domain'
description: 'Canonical identity-mapping spec for systems that mix managed sessions with standalone/headless event sources.'
---

# Session Identity Truth — Spec

## What it is

A canonical specification for how session identity is resolved when a system supports both:

- managed sessions (system-launched), and
- headless/standalone event sources.

This spec prevents mis-attribution, duplicate sessions, and broken recovery paths.

## Canonical fields

Identity model documentation must include:

- explicit route definitions (managed route and headless route),
- identity source-of-truth per route,
- mapping storage location and key format,
- native identity fields (id + log/transcript reference),
- conflict resolution rules when multiple identifiers exist,
- restart/recovery behavior,
- failure checklist for wrong-attribution incidents.

Minimum required identity fields:

- system session id,
- native session id (if applicable),
- native log/transcript location (if applicable),
- mapping record (native -> system id).

## Allowed values

Route types:

- `managed`
- `headless`

Authority modes:

- `managed-marker-authoritative`
- `native-mapping-authoritative`

Recovery outcomes:

- `reassociate-existing`
- `mint-new-session`
- `defer-with-error`

## Known caveats

- Legacy compatibility paths often create hidden identity conflicts. Document and phase them out deliberately.
- If both managed markers and native mappings can apply, authority order must be explicit and testable.
- Session identity docs are only useful if kept in sync with runtime extraction and mapping code.
