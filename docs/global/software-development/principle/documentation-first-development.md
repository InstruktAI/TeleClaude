---
id: 'software-development/principle/documentation-first-development'
type: 'principle'
domain: 'software-development'
scope: 'global'
visibility: 'public'
status: 'mixed'
delivered_by: ['snippet-status-framework']
description: 'Documentation leads, implementation catches up. Snippets declare current vs. target state explicitly so the gap stays honest and the design stays shareable.'
---

# Documentation-First Development — Principle

## Principle

Documentation is the source of truth for what the system is AND what it is becoming. Design happens in the document layer first; code catches up. A snippet that describes the intended shape of the system is not a wish or a forecast — it is the design, written down, shareable, reviewable, and binding on what gets built.

For this to work without becoming a fiction, snippets carry an explicit **status**:

- **`actual`** — describes the current implementation. The snippet matches what the code does today.
- **`target`** — describes the intended state. The snippet declares what the system will become; it does not yet match the code. The snippet lists the delivery slugs (`delivered_by`) that will close the gap.
- **`mixed`** — the snippet contains both. Sections within mark themselves so readers can tell what is current and what is intended.

This status indicator is the discipline that lets you write design directly into the documentation layer without lying about reality. A `target` snippet is honest about being aspirational; a reader trusts what they see because the snippet declares its own status. The design is shareable across agents and humans the moment it's written. The system gets a stable reference everyone can align to, including future-you.

When the delivery slugs in `delivered_by` reach `delivered`, the snippet flips from `target` to `actual`. The reconciliation is enforced by the system, not left to memory.

## Rationale

The alternative — designing inside todos, inside PRDs, inside scattered artifacts — fragments the design surface. Each todo's artifacts are local to that todo. Other agents working in parallel can't easily reference them. The orchestrator that needs to coordinate three related deliveries has to read three different PRDs to see the shared design. Conversations about future state degrade into "go read the X artifact in todo Y."

The alternative on the other side — refusing to update docs until code lands — leaves the design unspoken between conception and delivery. The product owner thinks about the future constantly; the agent reading docs sees only the past. There's no shared surface where forward design lives. So forward design ends up in chat, in Slack threads, in mental models that don't propagate.

Doc-first resolves both by making the design space first-class:

- **Shareable.** A target snippet is a URL all agents can reach. The design lives in one place, not five.
- **Honest.** The status flag prevents confusion. A reader knows whether the snippet describes current behavior or intended behavior.
- **Reviewable.** Target snippets get the same review surface as code — pull requests, lint, validation. Bad design gets caught at doc time, before implementation costs are spent.
- **Aligned.** The orchestrator dispatching three related builds points all three at the same target snippet. The builders read the same design. Their outputs converge.
- **Reconciled.** When delivery lands, the snippet flips. Stale "future" doesn't accumulate.

This is the same shape as TDD, schema-first API design, and ADRs. The discipline isn't new — what's new is naming it for documentation, encoding it in frontmatter, and making the reconciliation automatic.

## Implications

### 1. Snippet frontmatter carries `status` and `delivered_by`

Every snippet declares its status. The defaults are conservative:

```yaml
status: actual          # default for existing snippets and new code-grounded snippets
```

```yaml
status: target          # for forward design
delivered_by: [slug-a, slug-b]   # required when status is target or mixed
```

```yaml
status: mixed           # body describes some current state and some intended state
delivered_by: [slug-a]
```

Validation rules:
- `status: target` and `status: mixed` REQUIRE a non-empty `delivered_by` list.
- `status: actual` FORBIDS `delivered_by` (no orphan delivery references on snippets that already reflect reality).
- `delivered_by` references must be valid todo slugs (validated by `telec sync`).

### 2. The prepare phase authors target snippets

The prepare orchestrator already runs on `main` with no worktree — it's authorized to write snippets to the canonical doc layer. Authoring or updating the target snippet for the work being prepared is now a regular prepare deliverable:

- The PRD includes a "snippets to author or update" section listing the snippets the delivery will produce or change.
- The prepare worker writes the target snippets to `docs/` as part of preparation, marked `status: target` with `delivered_by` pointing at the slug being prepared.
- The plan reviewer verifies the snippets exist, accurately describe the intended state, and that the implementation plan delivers what the snippets promise.
- The snippets land on `main` via the normal prepare commit flow, before any work-phase worktree branches off.

The work phase then has the target snippets as the authoritative design reference. Build workers reference them directly; reviewers check the build against them.

### 3. Delivery flips `target` to `actual`

When a todo reaches `delivered`, the integrator (or the finalize step, depending on which role owns the reconciliation pass for the project) flips any snippet whose `delivered_by` list includes the delivered slug:

- If the slug was the ONLY entry in `delivered_by`, the snippet becomes `status: actual` and `delivered_by` is removed.
- If there are still pending slugs in `delivered_by`, the slug is removed from the list and the snippet stays `target` (partially delivered; remaining slugs still in flight).
- `telec sync` catches drift: any snippet whose `delivered_by` contains slugs that are all delivered must be flipped — failing to flip is a lint error.

### 4. Discoverability surfaces ownership

`telec docs index` renders the status and the owning slugs inline for every non-`actual` snippet — `actual` snippets render with no prefix, `target` and `mixed` snippets render with a bracketed prefix that names the status and the `delivered_by` slugs. The same listing answers "what is the state of this snippet?" and "who is on the hook to close the gap?" without a second lookup.

A worker preparing or building a slug runs `telec docs index --target <slug>` to see exactly which snippets it owns. This is the canonical query that makes the doc-first discipline operational rather than aspirational: the worker asks the system what it has been put on the hook for, and the system answers.

### 5. Domain specs are typically target before they're actual

A per-context domain spec (see `software-development/spec/domain-spec`) for a service that is being rewritten is authored as a `target` snippet, with `delivered_by` listing the slugs that will deliver the rewrite. Workers on the new implementation build against the target spec. When the new implementation ships and cuts over, the domain spec flips to `actual`. The parity check verifies the flip is honest — that the running system actually satisfies what the spec describes.

This is the structural reason a service rewrite is safe under this discipline: the domain spec is the shared target; both the old implementation (in its declining role) and the new one (in its ascending role) must satisfy it; the cutover happens when the new implementation satisfies the same spec the old one satisfies.

### 6. Hand-edits to snippets follow the same discipline

When you edit a snippet directly (as a human, mid-conversation, refining design), you mark it `target` if the edit describes intended state. You add a `delivered_by` pointing at the slug that will materialize the change. If no slug exists yet, you create one first (even an empty draft) and reference it.

The product owner habit of "update the doc to anchor my thinking" is welcome — it becomes a `target` edit with the delivery slug attached. The anchor is preserved; the reality gap is named.

### 7. `actual` is not a snapshot — it's a contract

A snippet marked `actual` claims to describe the current system. If the code changes and the snippet doesn't, the snippet is wrong. The reviewer of any code change checks whether the change invalidates any `actual` snippet; if it does, the change either updates the snippet (preferred) or marks the snippet `target` with the change's slug as the deliverer-of-the-update. Stale `actual` snippets are defects.

## Tensions

- **`target` snippets that never deliver.** The slug they point to may be deferred, frozen, or abandoned. The system flags this: a `target` snippet whose `delivered_by` contains only frozen / removed slugs is invalid. The author must either revive the delivery (unfreeze the slug) or convert the snippet back to `actual` (reverting the target content to reflect current state) — design that nobody is actually committing to deliver doesn't belong in the doc layer.

- **Design churn during prepare.** Target snippets may go through multiple revisions as the PRD iterates. Each revision is a commit on main. The history of how the target evolved is visible but adds noise. The discipline: only commit the snippet update when the prepare phase has converged on a stable design (typically: after spec/plan review), not on every intermediate draft.

- **Cross-context target snippets.** Some snippets describe intentions that span multiple bounded contexts (e.g., a new event taxonomy used by three services). The `delivered_by` list captures the slugs that deliver each part; the snippet may stay `target` until all parts deliver, or may flip to `mixed` with section-level marks as parts land.

- **The product owner's anchor vs. the agent's ground.** A product owner reading `target` snippets to track their own design intent sees forward state. An agent reading the same snippets to make a code decision needs current state. The inline status prefix in `telec docs index` keeps the distinction visible at the listing level — but the human-vs-agent reading style still needs to match the situation. When a human writes "in our system, X works like Y" as a target snippet, the human is asserting design; an agent reading later must check the status and not assume X works that way today.

- **Doc-first vs. discovery.** Some design only becomes clear after touching the code (the agent discovers the actual aggregate boundary by trying to model it). The discipline: it's fine to draft a `target` snippet, attempt the work, learn from the discovery, revise the `target` snippet, then deliver. The doc-first principle doesn't require you to be omniscient at design time; it requires you to write down what you learn AS you learn it, in the doc layer, with status honesty.

- **Doc-first vs. velocity for trivial changes.** A one-line bug fix doesn't need a target snippet authored before the fix lands. The discipline scales with the size and reach of the change. Changes to public surfaces, domain models, events, or contracts get doc-first treatment. Implementation-internal fixes update `actual` snippets as part of the fix if anything documented changed, and otherwise don't touch the doc layer.
