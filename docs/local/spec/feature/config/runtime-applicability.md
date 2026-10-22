---
description: Schema-owned machine applicability and one availability decision shared
  by configuration surfaces and feature entry boundaries.
---

# Runtime Applicability — Spec

## What it is

The configuration owner decides whether a declared field or section applies on
this computer. Features consume that decision before using the associated
configuration or starting its effects. The decision is local: machine files and
their existing credential references retain their storage authority under
`local/projects/teleclaude/spec/teleclaude-config`.

Applicability, enablement and completeness are separate inputs to one
configuration-owned availability answer. Keeping their interpretation with
configuration follows `sdlc/policy/domain-ownership`; consumers retain their
own operation outcome and presentation.

## Canonical fields

### Declaration and inheritance

Machine-schema scope metadata declares applicability on a field, nested section
or whole section. An undeclared scope inherits its enclosing scope; the root
default and supported scopes belong to the existing configuration schema.
Master scope applies only when this computer's master declaration holds.
An inapplicable enclosing section keeps its descendants inapplicable, including
descendants with local scope or an enabled value of their own.

The configuration owner resolves the complete schema path, including inherited
scope, governing enablement and the existing component-owned completeness
requirements. A field with no enablement switch still has an applicability
answer. Schema walking, runtime decisions and operator surfaces use the same
scope resolution, under `sdlc/principle/design-fundamentals`.

### Availability and entry boundaries

Availability distinguishes an inapplicable configuration dependency, an
applicable but disabled feature, an enabled but incomplete configuration, and
an available configuration. Inapplicability takes precedence over missing
credentials; inactive configuration produces no missing-credential requirement.
The answer contains safe field identities and reasons, never secret values.

A feature binds its configuration dependency at its startup, registration or
direct-operation boundary. That boundary consults availability before client
construction, handler registration or the protected effect. An unavailable
direct operation returns its existing explicit refusal or disabled outcome;
absence of execution is never reported as successful work. Work admitted through
the boundary consumes the resolved configuration without repeating scope checks.

A mixed component keeps its independently applicable functionality. A
master-owned effect within it evaluates master applicability at that effect's
entry boundary; it does not make the component's other configuration
master-scoped. Domain decisions such as interaction ownership and caller
clearance retain their owners under `sdlc/policy/domain-ownership`.

### Files, validation and operator surfaces

Scope changes runtime consumption, not stored declarations. Loads and ordinary
edits preserve inactive stored values; becoming a non-master deletes no file
content or credential. Master-scoped values permit omission on a non-master
through their schema's existing optional/default representation. Supplied
declarations retain ordinary document-shape and type validation under
`local/projects/teleclaude/spec/feature/config/unknown-key-warning`.

Readiness, field editability and configuration generation consume the same
resolved applicability. An inapplicable field is not an editable or required
operator input. Existing inspection surfaces may identify it as not applicable
without resolving or exposing a credential. Machine generation omits
inapplicable inputs once the computer's role is known; generic schema publication
continues to describe all supported fields.

Configuration changes use the existing validated file writer and reload/restart
boundary. A restarted feature resolves applicability from the newly loaded
configuration; this contract adds no independent live reconfiguration loop
(`local/projects/teleclaude/spec/feature/config/machine-config-load`).

## Known caveats

- Applicability is not fleet coordination. Two computers can declare themselves
  master; this contract supplies no election, transfer or uniqueness guarantee.
- A disabled or inapplicable feature does not make malformed supplied
  configuration valid. Runtime credential readiness and document validity are
  different judgments.
- An available configuration does not establish provider reachability, a valid
  remote login or successful execution; those outcomes belong to the consumer.
