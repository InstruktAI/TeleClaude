---
id: 'general/procedure/adr-authoring'
type: 'procedure'
domain: 'general'
scope: 'global'
visibility: 'public'
activation_trigger: 'Use when capturing an architectural or design decision as an ADR'
description: 'Author an Architectural Decision Record (ADR) capturing what was chosen, why, and what follows. Used by every agent that makes a non-trivial decision while authoring doc snippets, agent artifacts, or architecture changes.'
---

# ADR Authoring — Procedure

## Required reads

- @~/.teleclaude/docs/general/policy/adr-discipline.md
- @~/.teleclaude/docs/general/spec/snippet-authoring-schema.md

## Goal

Capture a decision as a structured, discoverable record that future agents can find, evaluate, and (if needed) supersede — without polluting the primary artifacts (specs, procedures, principles) with reasoning logs.

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
   id: project/adr/NNNN-kebab-case-title
   type: adr
   domain: software-development
   scope: project
   visibility: public
   number: NNNN
   date: YYYY-MM-DD
   adr_status: accepted # or proposed | deprecated | superseded
   description: <one-line summary of the decision>
   # optional:
   # supersedes: [project/adr/0001-prior-decision]
   ---
   ```

4. **Write the body** with the required H2 sections in order:
   - `## Context` — the situation that made this decision necessary. What were we trying to accomplish? What constraints or forces were in play? Brief and factual; not a history of the conversation.
   - `## Decision` — what we chose, stated as a decision. Active voice. One paragraph or a tight bullet list. The artifact this ADR justifies should reflect this decision.
   - `## Consequences` — what follows from this decision, positive and negative. What's now easier? What's harder? What's now precluded? What invariants must be honored going forward?
   - `## Alternatives Considered` (optional but encouraged) — what other paths were on the table and why they were rejected. Be honest; don't write retroactive justifications.

5. **Sanity check before commit:**
   - The decision is stated clearly enough that a future agent could re-evaluate it on its merits.
   - The consequences include the negative ones, not just the wins.
   - The ADR is discoverable: filename matches `id` frontmatter; number matches filename prefix; date is correct; status is accurate.

6. **Update related artifacts.** If this ADR supersedes a prior one:
   - Set the new ADR's `supersedes` frontmatter to the prior ADR's id.
   - Update the prior ADR's `adr_status` to `superseded`.

## Outputs

- A new file at `docs/project/adr/NNNN-<title>.md` containing Context / Decision / Consequences (and optional Alternatives Considered).
- If superseding: the prior ADR's `adr_status` set to `superseded`.

## Pre-completion checklist

- Filename matches `NNNN-kebab-case-title.md`.
- `number` frontmatter matches the prefix.
- `date` is ISO-8601 (`YYYY-MM-DD`).
- `adr_status` is one of the allowed values.
- All required sections present (Context, Decision, Consequences).
- Decision is stated as a decision, not a question or a narrative.
- Consequences cover both directions (positive and negative).
- If superseding, the prior ADR has been updated.

## Discipline

The single most-violated rule here is honesty about alternatives and consequences. Agents writing ADRs after the fact tend to construct retroactive justifications — listing alternatives only to dismiss them, naming only positive consequences. That defeats the ADR's purpose: future agents need an honest record so they can fairly re-evaluate the decision when context changes. If the decision was made under pressure, say so. If the chosen path has known costs, name them. The ADR is for future agents who do not have the present's context; write it for them, not for self-defense.

## Recovery

- An ADR with the wrong number can be renamed (file + frontmatter `id` + frontmatter `number`). Other ADRs that reference the renumbered ADR via `supersedes` must be updated.
- An ADR that should have been written but wasn't can be written retroactively. The `date` should reflect when the decision was actually made, not when the ADR was written. Note the retroactive nature in the Context section.
- An ADR with the wrong status (e.g., `accepted` when it should now be `superseded`) is fixed by updating the `adr_status` frontmatter only — the body stays as the historical record.

## See Also

- ~/.teleclaude/docs/general/policy/adr-discipline.md
