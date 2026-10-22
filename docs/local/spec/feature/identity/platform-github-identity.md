---
description: Infrastructure-bound GitHub App actors, protected installation credentials and session provenance, separate from human account bindings.
visibility: internal
delivered_by:
  - issue-129
---

# Platform GitHub Identity — Spec

## What it is

Identity owns the platform actor assigned to a session and the evidence binding
a GitHub invocation to that session. A human's declared GitHub account is a
separate binding under
`local/projects/teleclaude/spec/feature/identity/person-context-binding`.
Neither a person's account, native login, lineage nor an envelope selects a
platform credential (`sdlc/policy/ai-agent-security`).

## Canonical fields

### Actor assignment and invocation evidence

The infrastructure-owned session binding retains the assigned App and its bot
account identity, project/repository and target item. Role resolves from the
session record through
`local/projects/teleclaude/spec/feature/identity/agent-roles`; a caller-supplied
role or session identifier supplies no authentication. Driver and child of a
phase have different App bot accounts. Sessions may share an App without
sharing producing-session provenance. Refresh and restart preserve the assigned
actor (`sdlc/policy/ai-agent-security`).

The managed native boundary identifies an invocation only from freshly
corroborated facts for the actual open local session: a valid session marker,
its recorded project context and role state, the live pane on the platform's
configured tmux server, and PID/create-time ancestry connecting this process to
that pane. Current session, recorded role, work-binding and pane facts are reread at the
decision boundary. Missing, closed, remote, detached, inaccessible, ambiguous
or disagreeing evidence refuses the bound operation. A missing marker cannot
turn a known managed invocation into native human pass-through; uncertain
execution remains a refusal (`sdlc/policy/ai-agent-security`).

The observation distinguishes a genuinely absent stored role from a present
role that is unknown to the canonical catalog. The latter refuses and is never
normalized to absence. A genuinely absent role is carried only as native scope
evidence; it authenticates no caller and supplies no GitHub authority. The
GitHub-bound context factory still requires a canonical role before actor,
target or credential admission. Admitted daemon context also requires its
canonical role and uses the admitted caller, never native pane evidence.
Positively corroborated human execution outside managed panes retains native
behavior (`local/projects/teleclaude/spec/feature/identity/agent-roles`).

Actor assignment is durable session state; authentication of an invocation is
re-observed at execution. Restart reads current session facts and live process
evidence, never a remembered authentication verdict. The session owner persists
the binding through its existing durable records; there is no second session
registry or role/phase authority (`sdlc/policy/domain-ownership`).

Every session the workflow starts for an item carries that item's
(`WorkItemId`, `StoreAddress`) pair in one typed session-creation value that
only in-daemon producers set; no API, command-line or relayed request supplies
it. A phase driver receives the pair from its activation
(`local/projects/teleclaude/design/architecture/procedure-activation`). A phase
child receives it from the child launch, which reads the pair of the item its
holding driver claims through the store port before the child's session is
created; an address that resolves to nothing or cannot be read refuses the
launch (`local/projects/teleclaude/spec/feature/workflow/item-acts`, The child
command).

In a project whose selected workflow backend is GitHub (#124 INV-B1), every
session the workflow starts for an item requires both its actor assignment and
its native target. Both commit with the session row
and its startup handover in the one session-creation write, or nothing commits
and creation is refused, so restart never finds an unbound startup handover to
resume. The native target is the GitHub adapter's projection of the project's
repository identity and the carried (`WorkItemId`, `StoreAddress`) pair
(`local/projects/teleclaude/design/architecture/workflow-store`, #124 INV-D1);
it is never formed from a slug or from origin metadata. With a local backend the
creating write records neither binding. A session's scope is bound once and is
never rebound. The bound target names no branch or base: an operation that
needs them receives them in its request, from authoritative workflow state.

### Credential component

The session owner fixes the assigned App and stable Bot identity when it creates
the session and preserves that binding across role-map edits and restart.
Credential use consumes that durable session assignment; request content or a
caller-supplied role cannot select another actor. After caller authentication
and provider-operation admission, the credential component asks the config
owner for the key belonging to that assigned profile as a `SecretStr`. The
global declaration and key-resolution contract is owned by
`local/projects/teleclaude/spec/domain/config` and
`local/projects/teleclaude/spec/teleclaude-config`.

The credential component passes the config-owned secret answer to the existing
App authentication path. It receives no raw config mapping and never chooses a
secret file or environment fallback (`sdlc/policy/ai-agent-security`).

A config-owned credential refusal stops the operation without secret fallback
or value disclosure; an authenticated actor mismatch remains an identity-owned
refusal. See the config resolver and its file-custody owner:
`local/projects/teleclaude/spec/domain/config` and
`local/projects/teleclaude/spec/feature/config/atomic-env-file-write`.

The credential component authenticates the assigned App, resolves its target
installation and mints a repository-scoped installation token for the requested
permissions. Returned repository grants, permissions and expiry must satisfy
the request. Renewal retains the same App and bot account; missing, revoked,
expired, unauthorized or mismatched credentials refuse without another actor
or human-login fallback. Verification uses authenticated App/installation
metadata and provider-returned stable account identifiers and account type,
not an installation-token request to the human-account identity endpoint
(`sdlc/policy/security-awareness`).

Public App, installation and account identifiers and protected secret references
may be retained by their configuration/identity owners. Private keys remain in
protected credential storage; JWTs and installation tokens remain in credential
component memory. Tokens reach only the authorized child provider process's
startup environment or protected credential transport. Native credential stores,
agent-visible parent environments, arguments, configuration documents,
artifacts, prose and logs receive no token. Errors use the existing credential
masking boundary and disclose only identifiers and missing prerequisites
(`sdlc/policy/ai-agent-security`).

Native GitHub execution receives process-local credentials after structural
transport admission under
`local/projects/teleclaude/spec/feature/integration/github-posting`.
Computer-wide native auth switching and token disclosure are refused before
native execution. Credential selection never modifies shared login/keychain
selection, installs an App token in a human login store or borrows a person's
native authentication (`sdlc/policy/ai-agent-security`).

### External prerequisites

An authorized external operator supplies distinct production Apps, verified
App/bot identifiers, protected corresponding private keys, target repository
installations and sufficient scoped grants. An outside-owner repository needs
that owner's permitted installation/access path. Missing prerequisites produce
a concrete refusal; implementation alone supplies no production setup or
activation evidence (`general/policy/human-contract`).

### Cross-context references

- Config owns declarations and protected secret references; identity owns what
  a resolved account/session association establishes.
- The session owner stores bindings; posting consumes their authenticated facts
  and owns provider-object associations under
  `local/projects/teleclaude/spec/feature/integration/github-posting`.
- Workflow owns canonical performer, holder, phase, revision and head decisions
  under `local/projects/teleclaude/spec/feature/workflow/item-lifecycle` and
  `local/projects/teleclaude/spec/feature/workflow/item-acts`.
- Push and PR-authorship verification is
  `local/projects/teleclaude/spec/feature/integration/github-publication`.

## Known caveats

The managed-wrapper checks are guardrails on a host whose agents share an
operating-system user. A process controlling that account, its session records
or tmux server can tamper with those sources. This boundary does not make the
daemon's carried caller headers unforgeable or repair platform-wide caller
transport (`sdlc/policy/ai-agent-security`,
`local/projects/teleclaude/spec/identity-and-auth`).

An unavailable credential or provider request supplies no current workflow
state. Failure is contained to the operation; the daemon remains available
(`sdlc/policy/code-quality-practices`).
