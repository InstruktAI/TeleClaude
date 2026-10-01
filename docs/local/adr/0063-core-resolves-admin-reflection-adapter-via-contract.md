---
visibility: public
number: 0063
date: 2026-07-05
description: Core resolves the admin-reflection adapter through a capability Protocol, not a concrete DiscordAdapter import or an origin-based lookup.
---

# Core Resolves the Admin-Reflection Adapter via Contract — ADR

## Context

`CommandService._handle_escalate_session` needed to open an admin-relay thread
for a customer escalation. The existing code imported `DiscordAdapter`
concretely from `teleclaude.core.command_service` and looped
`isinstance(adapter, DiscordAdapter)` over the registered adapters — a direct
violation of the platform's adapter-boundaries rule that core never imports
adapter modules, and a hard-coupling that fails closed the moment Discord is
absent from the registry regardless of why escalation was requested.

Discord is documented (`project/spec/session-output-routing`) as the single
admin adapter: escalation opens a thread in the Discord admin forum
_regardless of the customer's own origin_ — a Telegram or WhatsApp customer
still escalates into Discord. That ruled out resolving the admin adapter from
`session.last_input_origin`, since a non-Discord-origin session would then
fail to resolve an admin adapter at all.

## Decision

Core resolves the admin-reflection adapter through a `@runtime_checkable`
`Protocol` (`AdminReflectionAdapter`, declared in `teleclaude/core/protocols.py`
alongside the existing capability protocols) that declares the
`create_escalation_thread` surface. `_handle_escalate_session` iterates the
adapter registry and selects the adapter that satisfies the Protocol
structurally — no import of the Protocol is required on the adapter side, and
no platform name is hardcoded in core. Discord's `AdminReflectionMixin`
satisfies the Protocol by shape.

## Consequences

- Core no longer imports any concrete adapter module to perform escalation
  resolution, matching `project/policy/adapter-boundaries` and the delivery
  Router's existing precedent of resolving adapters by capability rather than
  by concrete class.
- A future second admin platform can be adopted by implementing the Protocol
  on its own adapter class; no wiring changes are needed in core, and no
  adapter that doesn't support admin-reflection needs to reference the
  Protocol at all — it simply doesn't satisfy it.
- Escalation still targets a single admin surface today. If a platform ever
  needs per-session admin routing (multiple satisfying adapters), the current
  first-match resolution over the registry would need to be revisited; this
  decision does not address that case.
- Structural (duck-typed) Protocol satisfaction means a class that
  accidentally defines a same-named, same-shaped `create_escalation_thread`
  method would also satisfy the Protocol even without intending to act as an
  admin-reflection adapter. This is an accepted trade-off of `runtime_checkable`
  Protocols in Python; the method name is specific enough that accidental
  collision is unlikely in practice.

## Alternatives Considered

- **Resolve via `session.last_input_origin`.** Rejected: escalation is
  admin-targeted, not origin-targeted — a non-Discord-origin session must
  still resolve an admin adapter, which an origin-keyed lookup cannot do for
  origins that have no admin surface of their own.
- **String-keyed `"discord"` resolution** (matching the adapter registry by a
  hardcoded platform-name string, as `Router.resolve_admin_output_target`
  does for delivery routing). Rejected for this call site: it would keep a
  platform name embedded in core rather than expressing the actual capability
  core depends on.
