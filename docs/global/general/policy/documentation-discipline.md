---
description: 'The enforceable rules of doc-driven development: doc-only work is never a todo, functionality work authors its snippets first, and every behavioral delta is reflected in the doc layer.'
visibility: 'public'
---

# Documentation Discipline — Policy

## Rules

### Routing: documentation vs functionality

- **Doc-only changes are never promoted to a todo.** When a change touches
  documentation only — doc snippets, ADRs, README, no functionality — the agent
  and the human execute it **in-context, immediately** (on `main`, per the doc
  scope of `telec code commit`). The todo/lifecycle path exists **only** for work
  that delivers functionality. Promoting doc-only work to a todo discards the live
  design context that makes it correct and re-derives it cold; that is a violation.
- **Doc-only is not review-exempt.** In-context execution is not unreviewed
  execution. A doc-only commit that changes a doc snippet still requires an
  **independent** doc-hygiene review: the authoring agent may NOT review a snippet
  it wrote — it believes its own work is correct, which is no review. After the
  in-context commit, dispatch a reviewer via `/next-review-commits` on the commit
  SHA, at the thinking mode the reviewer rule in `general/procedure/orchestration`
  resolves for the scope; it runs the doc-hygiene lane over the
  changed snippets — a narrow, cheap check that they meet the contract
  (present-tense, no narration). This does not make doc-only work a todo: the
  reviewer reads the committed diff, it does not re-author, so the live design
  context is preserved. Config/state/README-only commits with no doc snippet need
  no review.
- **Functionality changes are doc-driven — snippets first.** Creating a todo that
  delivers functionality requires authoring or updating the affected doc snippets
  **up front**, pending, with `delivered_by` naming the delivering slug, as part
  of creating that todo. The planner shapes the doc work into the plan; the builder
  then executes against snippets that are already touched, and does not decide doc
  reflection on its own.

### Reflection: the doc layer tracks reality

- **Every behavioral delta is reflected in the doc layer.** A change that alters
  or adds a documented contract updates the corresponding snippet
  (spec / principle / policy / concept / ADR), or records an explicit
  `doc_impact_none: <reason>`.
- **A behavioral delta is a change to code-enforced, observable behavior — not to
  guidance prose.** Reflection triggers when the _contract_ a test could bind
  (`Given / When / Then`) changes. Advisory text a **human** reads — CLI help,
  menu copy, descriptive prose — _is_ its own documentation: editing it is a
  doc-layer-internal change that takes at most a doc-hygiene check, never a
  feature-spec use case. If no test could bind the change, it is not a contract
  delta and authors no use case.
- **Instruction text an agent acts on is executable contract, not advisory
  prose.** Where the reader is an agent and the words direct what it does — a
  runtime decision block, a dispatched worker's brief, a procedure step it
  follows — those words _are_ the implementation, and editing them changes
  behavior as surely as editing code. The preceding rule's escape hatch inverts
  here: that no test binds such text is what makes the change higher-risk, not
  lower, because nothing downstream catches it. Reflect it and review it as a
  behavioral delta. A commit that rewrites what an agent does is never labelled
  copy-only, wording, or "no logic change" — that label is itself the defect,
  because it routes a behavioral change away from every gate built to catch one.
- **A snippet without `delivered_by` is the current contract; staleness is a
  defect.** If code changes and a current snippet does not, the snippet is wrong —
  the change updates it (preferred) or adds `delivered_by` with the change's slug.
- **Pending state is carried only by `delivered_by`.** A live snippet is never
  overwritten in place to describe an undelivered change; the change is authored as
  a planned section or a companion. Mechanics live in
  `general/procedure/doc-snippet-authoring`; field shapes in
  `general/spec/snippet-authoring-schema`.
- **Delivery clears `delivered_by`.** The integrator folds the slug's planned
  sections and companions into the live contract and clears the field before the
  delivery commit — by machine, not by memory, and not by `telec sync`.

### Organization and boundaries

- **Feature specs are authored only for Category A work** (user-visible product
  capability). Category B (contract / surface refinement) and Category C
  (implementation-only) produce no feature spec.
- **Agent artifacts (commands, skills, agents) are not doc snippets** — they have
  no code to be pending against, so they carry no planned markers and no
  `delivered_by`. Their authoring lifecycle (human-decided, authored on `main`,
  never routed through a todo) is governed by
  `general/policy/agent-artifact-governance`.
- **When authoring or editing any doc snippet, load and follow**
  `general/procedure/doc-snippet-authoring` (how) and
  `general/spec/snippet-authoring-schema` (shapes).

## Rationale

Documentation leads and code catches up (`software-development/principle/documentation-first-development`).
This policy is the enforceable _rules_ layer of that disposition — kept separate
from the principle (the why) and the procedure (the how) so a rule is stated once.

The routing rules exist because the failure mode is mechanical: agents pattern-match
"big or structural" to "route it through the lifecycle," and propose a todo for
documentation. For doc-only work whose design was just established between the human
and the agent, a todo dispatches a fresh worker that never saw that context and
re-derives it — destroying the very input that makes the change correct. The
discriminator is **whether functionality is involved**, never size or apparent
formality.

## Scope

- All agents, all sessions, every documentation change, every domain.

## Enforcement

- A todo whose only deliverable is documentation must not be created; the work is
  executed in-context. Reviewers and the lifecycle treat a doc-only todo as a
  process violation.
- Plan-review applies the documentation lane as a hard gate (a behavioral delta
  with neither a snippet update nor a `doc_impact_none` justification blocks the
  plan); build-review and commit-review apply the docs lane as the backstop. See
  `software-development/policy/definition-of-done-lanes`.
- A doc-only commit that changes a doc snippet without a subsequent **independent**
  doc-hygiene commit-review is a violation. The authoring agent never reviews its
  own snippet; the review is a fast/medium reviewer over the committed SHA.
- Reviewers treat a stale current snippet as a defect.

## Exceptions

- Trivial implementation-internal changes with no contract change touch no docs —
  doc-first scales with the size and reach of the change.
