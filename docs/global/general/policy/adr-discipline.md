---
description: 'An ADR is created only for a real, contestable architectural decision; the default is none. Keeps the decision record minimal and high-signal, free of ceremonial noise, so primary artifacts describe the contract and agents spend no cycles on records that carry no fork.'
visibility: 'public'
---

# ADR Discipline — Policy

## Required reads

- @~/.teleclaude/docs/general/spec/snippet-authoring-schema.md
- @~/.teleclaude/docs/general/procedure/adr-authoring.md

## Rules

- An ADR records one real, contestable decision — a fork where genuine alternatives existed and one was chosen over them. It is created only for such a decision, and only because that reasoning is needed to work safely with what was built.
- The default is none. New and tightened contracts, clarifications, restatements, and alignment to already-settled decisions carry no fork and take no ADR. An unclear case takes none. An ADR is never produced preemptively, to satisfy a process step, or by clerical habit.
- The ADR is authored BEFORE or ALONGSIDE the primary artifact change, never retroactively long after.
- ADRs live at `docs/project/adr/NNNN-<kebab-case-title>.md` (peer to `spec/`, `design/`, `policy/`, `procedure/`, `concept/` — NOT under `design/`, because ADRs are reasoning records, not design exploration), follow the `type: adr` schema (Context / Decision / Consequences, with required `date` and `number` frontmatter), and are discovered via `telec docs index --areas adr`.
- Primary artifacts (specs, procedures, principles) MUST describe the _current state_ — they are NOT reasoning logs. The reasoning belongs in the accompanying ADR, not inline.
- The converse also holds: an ADR contains only the _why_ of a contested fork. Content that defines a term, states a contract, or describes current state is spec / policy / schema material, not ADR material. A record whose substance is definition, restatement, or current-state description carries no fork and is not an ADR — even when cast in the ADR form.
- When a snippet relates to an ADR, point to it from the snippet's `## See Also` section — a soft reference. Never name the ADR (or its reasoning) inline in the body as a parenthetical or clause; the body states the contract, `See Also` carries the pointer to the why.
- ADRs are immutable historical records. A later decision NEVER mutates an earlier ADR — not its body, not its standing. When a new ADR supersedes a prior decision, it cites the prior ADR's id in its own `supersedes` frontmatter; that forward pointer is the entire record of the relationship. The prior ADR stays exactly as written (it remains a true record of what was decided then). Any "superseded by" view is derived from the forward pointer, the same way a live snippet's `(superseded by: <slug>)` marker is derived from its companion's existence rather than stored on the parent — never by editing the superseded ADR.
- An ADR is one **atomic** decision — an immutable reasoning report on the architecture's decision timeline. One ADR records one decision. A cohesive contract whose parts must cross-reference is a spec or domain doc, not a set of mutually-referencing ADRs; each constituent decision is still its own standalone ADR.
- **ADR references run backward only.** An ADR may reference an _earlier_ ADR — a decision that already existed when it was written. It may NEVER reference a _later_ ADR, because at its moment that decision did not exist. The only _forward_ ADR-to-ADR link is `supersedes`, recorded on the newer ADR. (This governs ADR → ADR only; a spec or other snippet pointing at an ADR via its own `## See Also`, per the rule above, is unaffected and correct.)
- **An ADR records a decision, never work.** No todo, slug, `delivered_by`, delivery, or anything TBD appears in an ADR — those are not points on the decision timeline, and the future is not knowable from a past entry. ADRs sit outside the pending/delivery machinery: an `adr` snippet carries no `delivered_by` and has no companion file; it lands when its decision is made.

## Rationale

A decision record earns its place only by recording a real fork that future work depends on understanding. Two failures bound it. Reasoning smeared inline through specs and procedures turns primary artifacts into history logs that conflate "what is" with "what was considered," making them harder to consume. Records produced by reflex breed cross-reference clutter that costs every agent cycles to wade through and dilutes the signal of the records that matter. The discipline holds the record minimal and high-signal: primary artifacts describe the contract, and an ADR exists only where a genuine contested decision must be understood to work with what was built.

## Scope

All agents authoring or modifying:

- Doc snippets under `docs/`
- Agent artifacts under `agents/` or `.agents/`
- Architecture documents under `docs/project/design/architecture/` or `docs/project/design/architecture-v2/`
- Policies, principles, procedures, concepts, specs at any level

## Enforcement

- The doc-snippet-authoring procedure cross-references this policy: agents authoring snippets must consult ADR discipline as part of the procedure.
- The agent-artifact-authoring procedure cross-references this policy: agents authoring artifacts must do the same.
- Reviewers verify that any ADR present records a real, contestable decision, and reject a record produced for a change that carries no fork.

## Exceptions

- **Trivial changes.** Typos, formatting, example additions, reorganization without semantic change, broken-reference fixes. No ADR required.
- **Inventory documentation.** When documenting existing state that wasn't the result of a fresh decision (e.g., the v1-inventory feature snippets describing already-implemented behavior), no ADR is required for the inventory work itself. The decision was made when the original implementation landed; the inventory is just describing reality.
- **Internal-only changes inside a snippet's body** that don't reflect a decision — clarifying wording, restructuring a section for readability. No ADR.

When in doubt, write none. Doubt is the signal that no decision worth recording is present.
