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

The managed native boundary identifies its execution from observed process
ancestry and the session owner's live pane on the platform's configured tmux
server before credential access. A session marker identifies a candidate only;
its session, work binding and live pane ancestry must agree. Missing, closed,
remote, detached, ambiguous or disagreeing evidence refuses the bound operation.
A missing marker cannot turn a known managed invocation into native human
pass-through. Uncertain classification refuses; positively identified native
human execution outside managed agent sessions retains its native behavior
(`sdlc/policy/ai-agent-security`).

Actor assignment is durable session state; authentication of an invocation is
re-observed at execution. Restart reads current session facts and live process
evidence, never a remembered authentication verdict. The session owner persists
the binding through its existing durable records; there is no second session
registry or role/phase authority (`sdlc/policy/domain-ownership`).

A session created with an item's store identity
(`local/projects/teleclaude/design/architecture/procedure-activation`) in a
project whose selected workflow backend is GitHub (#124 INV-B1) requires both
its actor assignment and its native target. Both commit with the session row
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
