---
description: 'Maintain indexed project scratchpad workspaces for material shared in active collaboration or a concrete handoff.'
activation_trigger: 'Use when identified working material must be shared for active collaboration or a concrete handoff; and when joining, resuming, or promoting from an existing shared scratchpad workspace.'
visibility: public
---

# Scratchpad Workspace — Procedure

## Required reads

- @~/.teleclaude/docs/general/spec/scratchpad-workspaces.md

## Goal

Shared knowledge of the subject is reachable by the participants who need it.
A cold reader opens one directory, reads `index.md`, and finds the purpose,
current findings and designs, supporting evidence, material decisions, open
questions and any promoted results. Attribution identifies the sources and
contributors; the index is a map to the work, not a session diary
(`general/spec/scratchpad-workspaces`).

## Preconditions

- For the proposed write, a human or another session needs identified working
  material as input to active collaboration or a concrete handoff, under the
  exclusive-use contract in `general/spec/scratchpad-workspaces`.
- The project provides a version-control-ignored `scratchpad/` at the root of
  its canonical checkout (`general/spec/scratchpad-workspaces`).

## Steps

0. **Establish the shared purpose before every write.** Identify the human or
   session that needs the proposed material and the collaboration or handoff it
   serves. Apply the exclusive-use contract in
   `general/spec/scratchpad-workspaces`; proceed only when the proposed material
   meets it. Reassess updates to an existing workspace by the same criterion.
1. **Join before creating.** List `scratchpad/` for a workspace on the same
   topic — a peer's, or an earlier pass. Join it when it exists; one activity has
   one shared workspace. Otherwise create the directory the spec names. Publish
   the material that collaboration or handoff needs; local working material
   keeps its own environment (`general/spec/scratchpad-workspaces`).
2. **Write `index.md` first**, before any other file. Keep it a concise map to
   the subject and its useful material. Organize the information below where
   it exists; omit empty sections and link detailed findings rather than
   duplicating them. Apply the subject-knowledge boundary in
   `general/spec/scratchpad-workspaces` to both the index and its files:
   - **Status** — one line: `active`, `converged`, `closed`, or `abandoned`.
   - **Purpose** — the question the activity answers and the outcome it serves.
   - **Grounding** — the sources the activity rests on: what was read for
     current state, and how this class of problem is solved elsewhere, or that
     no prior art was found (`general/principle/grounding`). What is not yet
     grounded is listed as such. The section inventories evidence; it proves
     nothing about the reasoning built on it.
   - **Participants** — one row per session: session id, agent with model and
     thinking mode, role (author, peer, reviewer, dispatcher). The human appears
     by person slug. Session ids are the attribution evidence
     (`general/concept/lineage-vs-authorship`); `telec history show <session-id>`
     retrieves the reasoning behind each file.
   - **Files** — every file and subdirectory, a one-line purpose, and a status:
     `forming`, `converged`, `superseded by <file>`, or `promoted to <target>`.
   - **Stated by the human** — relevant intent and constraints, verbatim or
     near-verbatim, dated and retaining their qualifications. Preserve whether
     a statement is exploration, a suggestion or a decision; a technical idea
     is evaluated on its merits, not promoted to a requirement by attribution
     (`general/policy/human-contract`).
   - **Derived by agents** — conclusions agents reached, with the file that holds
     each. Distinguish findings, recommendations and settled decisions;
     evidence supports technical conclusions, while authorized intent bounds
     the outcome (`general/policy/human-contract`).
   - **Decisions** — material choices about the subject, their grounds and
     status, date, and who agreed, by session id or name. A decision is settled
     only when every active participant agreed
     (`general/principle/attunement`).
   - **Withdrawn** — conclusions retracted, by whom, and why, so no later agent
     re-proposes them.
   - **Open** — unresolved questions, with an owner when one is known.
   - **Promoted** — where agreed material landed: snippet ids, commit SHAs, todo
     slugs, published artifact URLs.
   - **Related** — relative paths to earlier workspaces this one builds on.
3. **Keep the subject's current state clear.** Update the index when useful
   material, a substantive conclusion, contributor attribution or a promotion
   changes. Revise the current account in place. Dispatches, retries,
   acknowledgements, session closure or revival, and the agent's corrections
   to its own conduct belong in session or workflow records; retain only a
   resulting design constraint, finding or concrete handoff dependency here
   (`general/spec/scratchpad-workspaces`).
4. **Name files for what they hold, never for their version.** Revise in place.
   When a rework must keep its predecessor, give the new file a descriptive name
   and mark the old one `superseded by <file>` in the index.
5. **Attribute inside files too.** A file that records human input keeps the
   human's statements apart from agent derivations, as the index does.
6. **Hand peers the path, not the content.** A kickoff or handoff names the
   workspace directory. A joining session adds its own Participants row before
   writing anything else.
7. **Promote selectively.** The procedure that owns the durable authority
   authors the agreed material there (`general/spec/scratchpad-workspaces`).
   Then record the target under Promoted, set each promoted file's status, and
   set the workspace Status.

### Examples

A minimal index can start with the fields below; add the other information
from Step 2 when it exists:

```markdown
# <Topic> — index

Status: active

## Purpose

## Participants

| Session | Agent / model / mode | Role |
| ------- | -------------------- | ---- |

## Files

| File | Purpose | Status |
| ---- | ------- | ------ |

## Open

## Sources
```

## Outputs

- One workspace directory under the project's `scratchpad/` whose `index.md`
  points to reusable subject knowledge and identifies current and superseded
  material.

## Recovery

- **Process diary displaces shared knowledge.** The workspace accumulates
  dispatch updates, closure/revival stories, acknowledgements or explanations
  of the agent's own mistakes. Reassess each entry against the future reader's
  question about the subject. Keep the findings, evidence, design implications
  and unresolved dependencies; remove the coordination narrative from the
  shared material and use the existing session/workflow record for it. A
  participant row supplies provenance without a lifecycle log
  (`general/spec/scratchpad-workspaces`).

- **Needed shared material is still in a local working directory.** Publish
  the material the collaborator or handoff recipient needs and index it, using
  the routing contract in `general/spec/scratchpad-workspaces`.
- **Joining or resuming a workspace with no index.** Write the index from the
  files present. Mark any author, date, or status you cannot establish as
  `unknown`.
- **A participant's session id cannot be established.** Record the row with
  agent, model, and role, and the id as `unknown`. Never guess an id.
- **The project has no ignored `scratchpad/`.** Write no working files into the
  checkout. Keep the material in conversation and report the missing ignore to
  whoever owns the project's setup.

## Discipline

Keep the workspace useful to the next reader of the subject: current
understanding, supporting evidence, choices and open questions, with clear
provenance and links. Apply this procedure to shared material under
`general/spec/scratchpad-workspaces`.
