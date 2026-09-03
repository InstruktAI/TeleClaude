---
description: 'Practical identity rules for assigning hooks to the correct TeleClaude session.'
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

- Managed identity is determined from the session identity marker before pane
  attachment is considered. The marker identifies TeleClaude lineage; the native
  session id and adapter-provided process kind identify the execution that emitted
  the hook.
- Pane attachment means attachment to a pane on TeleClaude's own tmux server, and
  the socket path carried by the tmux environment is what establishes it. A foreign
  harness that hosts an agent CLI inside its own tmux server also sets that
  environment, so the variable's presence alone carries no lineage. An invocation on
  a foreign socket has no pane attachment and is classified as though it were
  detached. Ownership fails closed: a socket path that cannot be parsed or resolved
  counts as TeleClaude's own, so a dying managed session keeps its attribution
  rather than minting a headless session from its final hooks.
- A valid marker with pane attachment is a managed-primary invocation. Its native
  identity may refresh the session's canonical native binding.
- A valid marker without pane attachment is a managed-descendant invocation. It
  resolves to the marker's TeleClaude session, retains its own native id in the
  hook envelope, and never mints a session or replaces the parent's canonical
  native binding. Provider process metadata may strengthen the descendant
  classification but is not the lineage authority.
- A marker that is present but malformed, stale, or bound to an incompatible
  session fails closed through managed fallback or event drop. It is never
  reinterpreted as permission to mint a headless session.
- A pane-attached invocation whose marker disappeared during teardown uses the
  live native-session fallback. A terminal or unresolved session is dropped.
<!-- planned-change:external-session-identity -->
- Only an invocation with neither a session identity marker nor pane attachment
  enters the headless route. It resolves through the native map and sessions store;
  an adapter mint event may create a new TeleClaude id only on this route. An agent
  CLI hosted by a foreign harness reaches TeleClaude on this route, and its stable
  native session id maps it to one durable session for the life of that conversation.
<!-- change:external-session-identity -->
- Only an invocation with neither a session identity marker nor pane attachment
  enters the headless route. An agent CLI hosted by a foreign harness reaches
  TeleClaude on this route. A session minted on this route carries a
  daemon-minted root process binding, established from the attested connection
  that delivered its session-start hook, and that binding is what later callers
  are matched against.
- The native session id is provider metadata on this route. It records which
  conversation a hook belongs to; it never selects a TeleClaude session for an
  authenticated caller, never rebinds a session to a different root, and never
  revives a session whose root has exited.
<!-- /planned-change:external-session-identity -->

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

- `managed-primary`
- `managed-descendant`
- `managed-teardown`
- `headless`

Authority mode:

- `native-mapping-authoritative`

Recovery outcome:

- `reassociate-existing`
- `mint-new`
- `tmux-contract-violation`
- `identity-contract-violation`

- `drop-orphan-teardown-hook`

## Known caveats

- Marker authority does not collapse execution identity: managed descendants retain
  their native session id and process kind on each forwarded hook.
- Provider-specific background-process signals are diagnostic classification input.
  Their absence cannot authorize headless minting when a managed marker is present.

- Native fields may be missing in some events; logic must handle that safely.
- This file is only useful if kept in sync with receiver + mapping code behavior.

**Identity representation invariant:** The full UUID must be used in every context where a
session ID appears — log fields, structured log kwargs, message bodies, notification text,
error strings, exception messages, and API response bodies. Truncation (`[:8]`, `[:12]`, or
any other slice) is never permitted on session, operation, or native IDs. The only permitted
exception: tmux session name labels (`tc_{session_id[:8]}`), which are UI display identifiers
and are never used as API keys or lookup values. Reviewers must reject any diff that introduces
`[:8]` or similar truncation on an identifier variable.
