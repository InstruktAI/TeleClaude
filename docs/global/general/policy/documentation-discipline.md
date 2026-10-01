---
description: 'The enforceable rules of doc-driven development: functionality authors
  its contract first, behavioral deltas stay reflected, and current versus pending
  truth remains explicit.'
visibility: public
---

# Documentation Discipline — Policy

## Rules

### The doc layer tracks reality

- **Every behavioral delta is reflected in the doc layer.** A change that alters
  or adds a documented contract updates the owning snippet, or records an
  explicit `doc_impact_none: <reason>`.
- **A behavioral delta is a change to code-enforced, observable behavior** — a
  contract a test could bind. Descriptive text (what exists, where to look, what
  a flag means) is its own documentation; editing it is a doc-layer change, not a
  contract delta.
- **Directive text on an agent-reachable surface is executable contract.** The
  discriminator is what the words _do_, never who reads them: text that tells its
  reader to take an action — a runtime decision block, a worker brief, a
  procedure step, a CLI message naming a next move — is the implementation.
  `--all runs against every configured source` is descriptive; `run make
restart, then check the logs` is directive. One string reaching a human and an
  agent alike resolves to contract. That no test binds such text makes the change
  higher-risk, not lower. Its remedy is exactly two things: reflect it in the
  owning snippet, and put the commit through independent review. It is never
  labelled copy-only, wording, or "no logic change."
- **A snippet without `delivered_by` is the current contract; staleness is a
  defect.** If code changes and a current snippet does not, the change updates it
  or marks it pending. Pending state and its clearing on delivery are
  `sdlc/principle/documentation-first-development`; the carriers
  are `general/procedure/doc-snippet-authoring`.

### Doc-driven delivery

- **Todo routing belongs to** `sdlc/policy/todo-creation-discipline`;
  this policy governs the documentation once routing is decided and grants no
  authoring authority.
- **Doc changes to what the human governs are written where the human is.** When
  the human, with the agent they address, decides something that changes a
  process whose outcome is theirs (the closed list in
  `general/policy/human-contract`), that agent writes the doc change itself,
  before any todo or delegated work that depends on it, and does not hand it to
  another agent. Any other doc change can be written up front, where the
  authoring session holds context a handoff would lose, or delegated, where
  nothing would be lost in translation.
- **Functionality is doc-driven — snippets first.** A todo that delivers
  functionality has its affected snippets authored or updated, pending, before
  its plan is drafted: by the creating session when it holds context a handoff
  would lose, otherwise by the claimant at preparation entry. The planner shapes that doc work into the plan; the
  builder executes against it and does not decide doc reflection on its own.
- **A feature spec is owed only for behavioral work delivered through a todo**,
  against the bounded context that owns the behavior; the classification and
  placement are `sdlc/principle/documentation-first-development`
  and `sdlc/procedure/feature-spec-authoring`. Global doctrine
  (policy, principle, procedure, spec) is directive text: reflected and reviewed
  as above, never given a use case.
- **Agent artifacts are not doc snippets** (`general/policy/agent-artifact-governance`).

### Review and cross-project authoring

- **Governed documentation is never self-reviewed.** A doc-only commit that
  changes a snippet gets an independent fast doc-hygiene review via
  `/review-commits` on its SHA, covering the security lane's
  repository-privacy check and the doc-hygiene lane. Both are reviewer judgment,
  never prose scanning. Standalone descriptive prose outside the snippet system,
  such as a README, is not governed content; directive text is, wherever it lives.
- **Cross-project doc work preserves the authoring session.** The session holding
  the design context writes the complete content to caller-owned temporary files
  and relays only their absolute paths and target repository paths to a session
  rooted in the owning project. That agent applies them exactly — no rewriting,
  summarizing, or improving — then runs its project's validation, sync, commit,
  and review routing. If it cannot apply them exactly, it reports the blocker and
  leaves the content unchanged. The caller removes the files once success or
  cancellation is confirmed.

## Rationale

Documentation leads and code catches up
(`sdlc/principle/documentation-first-development`); this policy
is that disposition's rule layer.

Reader identity cannot classify a surface that one string serves to both humans
and agents; what the words do can be read from the string itself, so every
reviewer resolves the same case the same way.

A decision the human makes with one agent reaches every other agent through the
document that agent writes. Handed on as a message instead, it arrives without
the conversation that made it correct, and the human is pulled back to restate
it.

An author reviewing their own snippet believes it correct, which is no review.

Moving a mechanical write to another project must not move authorship with it:
the files carry the already-authored document, and the receiving session owns
only application and its project's gates.

## Scope

All agents, all sessions, every documentation change, every domain.

## Enforcement

Plan-review applies the documentation lane as a hard gate; build-review and
commit-review apply it as the backstop
(`sdlc/policy/definition-of-done-lanes`). The independent
doc-hygiene commit-review catches self-reviewed and stale snippets.

## Exceptions

- Trivial implementation-internal changes with no contract change touch no docs.

## See Also

- ~/.teleclaude/docs/sdlc/policy/todo-creation-discipline.md — owns whether work executes in context or through a todo.
