---
activation_trigger: 'Use when capturing an architectural or design decision as an ADR'
description: 'Author an Architectural Decision Record (ADR) capturing what was chosen, why, and what follows. Used by every agent that makes a non-trivial decision while authoring doc snippets, agent artifacts, or architecture changes.'
visibility: 'public'
---

# ADR Authoring — Procedure

## Required reads

- @~/.teleclaude/docs/general/policy/adr-discipline.md
- @~/.teleclaude/docs/general/spec/snippet-authoring-schema.md

## Goal

Capture a decision as a structured, discoverable record that future agents can find, evaluate, and (if needed) supersede — without polluting the primary artifacts (specs, procedures, principles) with reasoning logs.

### What an ADR is

An ADR is one atomic, immutable reasoning report on the architecture's decision
timeline. It records a single decision at the moment it was made: the context and
forces then in play, the decision taken, and its consequences. It is history —
never edited after the fact.

Three constraints follow from that nature, and they are the rules most often
broken:

- **Atomic.** One ADR records one decision. A cohesive contract whose parts must
  cross-reference is a spec or domain doc; each constituent decision is still its
  own standalone ADR.
- **Backward-only on the timeline.** As a fixed point in time, an ADR may rest on
  decisions that already existed when it was written — referencing an _earlier_
  ADR is fine. It may **never** reference a _later_ ADR, because at its moment
  that decision did not exist. There is no forward link.
- **Decisions, not work.** An ADR records a decision, never work: no todo, no
  slug, no `delivered_by`, no delivery, nothing TBD. Those are not points on the
  decision timeline, and the future is not knowable from a past entry.

## Preconditions

- A non-trivial decision is being committed to documentation, agent artifacts, or architecture. (Per the ADR discipline policy: a future agent would reasonably ask "why was it done this way?")
- The agent has identified the ADR's number by inspecting `docs/project/adr/` for the highest existing number and incrementing.
- The agent has read the ADR discipline policy and the snippet authoring schema's `adr` type definition.

## Steps

1. **Pick the next number.** List the `docs/project/adr/` folder. Find the highest existing `NNNN-` prefix. The new ADR is `NNNN+1` (4-digit zero-padded).

2. **Pick a kebab-case title.** Short, action-oriented, describes the decision. Examples: `memory-uses-triples`, `event-store-semantics`, `provenance-via-mirror-id`.

3. **Create the file** at `docs/project/adr/NNNN-kebab-case-title.md` with the frontmatter shape:

   ```yaml
   ---
   visibility: public
   number: NNNN
   date: YYYY-MM-DD
   description: <one-line summary of the decision>
   ---
   ```

   Author only the fields above. `id`, `type`, `domain`, and `scope` are
   path-derived by the index — do not author them in the source frontmatter.

4. **Write the body** with the required H2 sections in order:
   - `## Context` — the situation that made this decision necessary. What were we trying to accomplish? What constraints or forces were in play? Brief and factual; not a history of the conversation.
   - `## Decision` — what we chose, stated as a decision. Active voice. One paragraph or a tight bullet list. The artifact this ADR justifies should reflect this decision.
   - `## Consequences` — what follows from this decision, positive and negative. What's now easier? What's harder? What's now precluded? What invariants must be honored going forward?
   - `## Alternatives Considered` (optional but encouraged) — what other paths were on the table and why they were rejected. Be honest; don't write retroactive justifications.

5. **Sanity check before commit:**
   - The decision is stated clearly enough that a future agent could re-evaluate it on its merits.
   - The consequences include the negative ones, not just the wins.
   - The ADR is discoverable: the path-derived id matches the filename; authored `number` matches the filename prefix; date is correct.

6. **Never modify a prior ADR.** A decision that reverses an earlier one is its
   own new ADR; the earlier ADR stays exactly as written. State the relationship,
   if it matters, in this ADR's prose as a backward reference — there is no
   supersession field.

## Outputs

- A new file at `docs/project/adr/NNNN-<title>.md` containing Context / Decision / Consequences (and optional Alternatives Considered).

## Pre-completion checklist

- Filename matches `NNNN-kebab-case-title.md`.
- `number` frontmatter matches the prefix.
- `date` is ISO-8601 (`YYYY-MM-DD`).
- All required sections present (Context, Decision, Consequences).
- Exactly one decision (atomic); a multi-part contract belongs in a spec, not split across ADRs.
- The body references only earlier ADRs, never a later one.
- The body references no work — no todo, slug, `delivered_by`, delivery, or TBD.
- Decision is stated as a decision, not a question or a narrative.
- Consequences cover both directions (positive and negative).
- No prior ADR was modified.

## Discipline

Two failure modes dominate. The first is **authoring an ADR as something it is not** — a work log that names todos, slugs, or deliveries, or a node in a cross-linked graph that points forward to decisions not yet made. An ADR is one decision, frozen in time, looking only backward (see § What an ADR is); when the impulse arises to cite a sibling ADR or a delivering slug in the body, that is the warning sign. The second is **dishonesty about alternatives and consequences**: agents writing after the fact construct retroactive justifications — listing alternatives only to dismiss them, naming only positive consequences. Future agents need an honest record so they can fairly re-evaluate the decision when context changes. If the decision was made under pressure, say so; if the chosen path has known costs, name them. Write for the future agent who does not have the present's context, not for self-defense.

## Recovery

- An ADR with the wrong number can be renamed (rename the file and update frontmatter `number`; the id re-derives from the path). Other ADRs or snippets that reference the renumbered ADR must be updated.
- An ADR that should have been written but wasn't can be written retroactively. The `date` should reflect when the decision was actually made, not when the ADR was written. Note the retroactive nature in the Context section.

## See Also

- ~/.teleclaude/docs/general/policy/adr-discipline.md
