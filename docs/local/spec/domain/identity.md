---
visibility: internal
description: Frozen v1 ownership anchor for caller identity resolution and authentication evidence.
---

# Identity Domain Spec — Spec

## What it is

The v1 identity area resolves local people, machines, terminals, and sessions
into caller identity used by CLI and API boundaries. It describes current
appliance behavior only; the replacement identity and access model lives in
TeleClaudeNext.

## Canonical fields

- **Current behavior:** `docs/local/spec/feature/identity/` and the auth
  feature specs that require this anchor.
- **Implementation roots:** `teleclaude/core/identity.py`,
  `teleclaude/session_identity.py`, `teleclaude/api/auth.py`, and
  `teleclaude/cli/telec/auth.py`.

- **Maintenance stance:** see `local/projects/teleclaude/spec/domain/glossary`. New tenancy, RBAC, and secrets
  architecture belongs to TeleClaudeNext.

### Ownership boundary

- **Owns:** principal resolution, authentication evidence, and the identity
  facts authorization decisions consume.
- **Also owns:** organizational relationship resolution — what a person's
  company membership, company role, and project assignment mean, and what
  resolving them reports. The declarations themselves are config's; identity
  reads them and reinterprets nothing.
- **Also owns:** person-context binding resolution — whether a person
  workspace's declared identity claim is accepted as binding that context to
  exactly one registered person, validated against the person registry, with
  unknown, ambiguous, and disagreeing claims failing closed. The declaration
  itself is config's; identity reads it and reinterprets nothing, and an
  accepted binding is an identity fact that grants no authority of its own.
  The behavioral contract is
  `local/projects/teleclaude/spec/feature/identity/person-context-binding`.
- **Does not own:** provider payload parsing, message delivery, session action,
  or workflow transitions merely because they carry a principal.
- **Published contracts:** resolved-principal and authentication-evidence types
  consumed at CLI, API, integration, and runtime boundaries.

- **Also owns:** the session company context that tools running inside a
  session read — the company, the origin (human-directed work with its human
  principal, or system-principal company work), and whether the company is
  resolved, absent, or ambiguous. The company is the session record's company
  when `agent_runtime` has set one; otherwise, for a human-lineage session
  whose person has exactly one eligible company, that company as resolved;
  otherwise unresolved, naming the eligible companies when several remain.
  Identity resolves it when a tool asks, from the session record that the
  session identity document's session id names and from its own membership
  resolution, and publishes it through `telec auth whoami`. The company lives
  on the session record alone: identity writes none of it into the session
  identity document, so no copy can disagree with the record, and the answer
  survives a restart because the record does. Readers consume the published
  answer and never re-validate it.

- **Also owns:** the agent role catalog — the closed set of session roles,
  the explicit capability set each composes, whether it is marked full-reach,
  its class, and its header label; and the resolution of a recorded role to
  that entry, a role outside the catalog resolving to a refused, reported
  defect and never to a human session. Command clearance, dispatch privilege,
  procedure role validation, standing classification, history exclusion,
  launch ownership and attribution consume it and keep no role list of their
  own. The behavioral contract is
  `local/projects/teleclaude/spec/feature/identity/agent-roles`.

- **Also owns:** reach — which platform records a principal may see. Identity
  resolves it once per request from the principal and its own facts (platform
  role, company rosters and their project assignments) together with config's
  project ownership. A long-lived consumer holds the resolved reach until a
  declaration identity reads changes, and never past that change. Reach admits a
  record by three facts the record carries — its subject, the subject's owner as
  resolved where the record was made, and the principal it is recorded under:
  - a platform administrator and the system principal: every record;
  - a company subject: every person on that company's roster;
  - a person subject: that person;
  - a project subject this computer registers: the owning company's
    administrators and the roster members assigned to it, or the owning person,
    read from the current ownership;
  - a project subject this computer does not register: the same test against the
    owner the record carries — an administrator of the carried owning company, a
    member whose roster in that company assigns the project, or the carried
    owning person;
  - the platform's shared documentation: additionally every company
    administrator;
  - a record recorded under the caller's own principal: the caller.

  A record with no subject, with a subject recorded as unknown because it could
  not be established, about an unowned project, or whose owner nothing resolves
  meets no subject rule: only platform reach and the caller's own principal
  admit it. An unknown subject is never read as no subject or as a home. A
  platform role below administrator admits nothing of its own; it still counts
  where authorization reads the effective role.

- **Published contract — reach:** one resolved value per principal with two
  appliers: a test of one record's facts, for streams and file-based data, and a
  query predicate over a store's subject, owner, and principal columns, applied
  before paging. Neither performs a lookup per record. Consumers own which facts
  their records carry and their own audience facts — public and person-local
  documentation, addressed notifications — and never add, relax, or re-derive
  reach. The behavioral contract is
  `local/projects/teleclaude/spec/feature/identity/data-visibility`.

- **Also owns:** a help desk's scope — the people a desk belongs to, who see its
  operator surface. A company desk's scope is that
  company's whole roster, members and admins alike. A company-owned project
  desk's scope is the owning company's whole roster. A person-owned project
  desk's scope is the owning person. Every desk's scope also includes the
  platform administrators. Identity resolves it from its own membership facts,
  config's project ownership and the platform roster, and reinterprets none of
  them. Desk scope is a separate answer from reach: for a company-owned project
  desk it admits company members that project reach does not. Because identity
  owns both answers, no consumer relaxes reach. A long-lived consumer holds a
  resolved desk scope only until a declaration identity reads changes. Its
  consumer is the help desk's Discord surface
  (`local/projects/teleclaude/spec/feature/integration/discord-admin-reflection-state`).

### Governing designs and decisions

- `local/projects/teleclaude/design/architecture/organizational-membership` — the company roster and its resolution
- `local/projects/teleclaude/design/architecture/scoped-roles` — person roles held at a scope
- `local/projects/teleclaude/design/cli-authorization-matrix` — which roles and bands may run each command
- `local/projects/teleclaude/design/architecture/local-caller-attestation` — the withdrawn local caller attestation design
- `local/projects/teleclaude/adr/0093-bind-mcp-credentials-to-verified-owner` — binding personal MCP credentials to the verified owner
- `local/projects/teleclaude/adr/0097-involvement-is-observed-not-adjudicated` — the involvement record resolved from observed input
- `local/projects/teleclaude/adr/0101-clients-authorize-and-the-daemon-trusts-carried-identity` — clients authorizing their caller and the daemon trusting carried identity
- `local/projects/teleclaude/adr/0103-person-roles-are-one-vocabulary-held-at-a-scope` — one person-role vocabulary held at a scope

## See Also

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
