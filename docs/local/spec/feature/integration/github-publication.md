---
description: Session-App-authenticated branch publication, repository-activity proof and creating-builder draft PR authorship, separate from integration delivery.
visibility: internal
delivered_by:
  - issue-129
---

# GitHub Publication — Spec

## What it is

Integration verifies that a branch update and the builder's work PR use the
platform actor established by
`local/projects/teleclaude/spec/feature/identity/platform-github-identity`.
Git commit authorship, human lineage, API identity and actual push authentication
are distinct facts (`general/concept/lineage-vs-authorship`,
`sdlc/policy/ai-agent-security`).

## Canonical fields

### Platform push

The existing publication path consumes the session's fixed actor and a
repository-scoped credential from its credential component. It confines the
effective transport to the intended canonical HTTPS repository and explicit
ref/head, neutralizing inherited URL rewrites, credential helpers, Git config
injection and SSH fallback without changing shared git configuration. Local
repository configuration and hooks cannot select another credential or
transport. Execution uses an isolated temporary git directory referencing the
worktree's objects, with controlled configuration and only the intended
destination/refspec (`sdlc/policy/security-awareness`).

Before sending a ref update, publication observes the prior remote ref. Success
requires the current ref/head and GitHub repository activity proving the exact
before/after/ref update was performed by the assigned stable actor identity.
Commit author fields, environment setup, a public clone or the general events
feed supply no push proof. An unchanged prior/desired ref is a no-op and
manufactures no new update evidence (`sdlc/policy/security-awareness`).

The integrator's existing authority over main, lease, ordering, guards,
maintenance and delivery remains
`local/projects/teleclaude/spec/feature/workflow/integration-state-machine`.
This transport makes no delivery decision and supplies no provider merge path
(`sdlc/policy/domain-ownership`).

### Builder draft PR

After the first confirmed platform push, the authenticated creating builder
opens its bound work branch's draft PR when none exists. Repository, head and
integration base come from the existing work binding. Creation supplies only
title/body and those resolved fields, with draft required; native mutation
limits are
`local/projects/teleclaude/spec/feature/integration/github-posting`.
The returned PR author must match the assigned actor, and the work driver's
review actor must differ. The PR/provider ID and verified creating
session/actor association are retained (`sdlc/policy/ai-agent-security`).

Discovery and retry reuse the work branch's existing PR. A mismatched existing
author or work binding is reported rather than repaired through another actor
or a second PR. The creating builder may maintain that PR's descriptive
title/body through the posting contract. The workflow/review owner retains
head validity, reviewed SHA and readiness decisions
(`sdlc/policy/domain-ownership`).

## Known caveats

A successful push process can leave a moved ref before activity verification
fails. Missing, unresolved or wrong-actor evidence is reported as unverified or
misattributed with the possible remote effect. It cannot count as a confirmed
platform push or authorize first-push draft creation. Publication does not
blindly repeat, rewrite or delete the ref to resolve that ambiguity
(`sdlc/policy/code-quality-practices`).

The isolated Git realization must preserve the existing native protected
rebase decision using the captured work ref, its matching remote-tracking ref
(or verified absence), and faithful snapshots of their source reflogs in a
files-backed repository. If those refs or reflogs are inaccessible,
inconsistent, or cannot be represented faithfully, publication refuses that
input. It does not synthesize history, weaken the protection to fast-forward
only, or replace Git's inclusion decision with a new engine.

Repository-activity reads are bounded observed corroboration, not a provider
causal receipt, atomic page-set snapshot, or guarantee against historical
backfill. Each pre-send and post-send traversal must complete within its
10-page limit and 30-second total phase budget, including its fixed remote-ref
read. Exceeded bounds, busy or incomplete pagination, and missing, delayed,
inconsistent or ambiguous evidence remain unverified with any possible remote
effect reported; they cannot authorize PR creation or replay. A verified empty
baseline requires a completed traversal. Generic pagination uses the existing
`gh`/GitHubKit surface; this contract adds no proof framework.

Production App setup and scoped content/push grants are prerequisites supplied
under the identity contract. A coordination push under an installed human login
or a correct commit author is not platform-App verification evidence
(`general/policy/human-contract`).
