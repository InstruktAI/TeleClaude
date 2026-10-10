---
description: 'Maintain indexed project scratchpad workspaces for material shared in active collaboration or a concrete handoff.'
activation_trigger: 'Use when identified working material must be shared for active collaboration or a concrete handoff; and when joining, resuming, or promoting from an existing shared scratchpad workspace.'
visibility: public
---

# Scratchpad Workspace — Procedure

## Required reads

- @~/.teleclaude/docs/general/spec/scratchpad-workspaces.md

## Goal

Shared working material is reachable by the participants who need it. A cold
reader opens one directory, reads `index.md`, and knows what the activity is
for, who contributed, which files are current, what was settled and by whom,
what is still open, and where agreed material went.

## Preconditions

- A human or another session needs identified working material as input to
  active collaboration or a concrete handoff, under the routing contract in
  `general/spec/scratchpad-workspaces`.
- The project provides a version-control-ignored `scratchpad/` at the root of
  its canonical checkout (`general/spec/scratchpad-workspaces`).

## Steps

1. **Join before creating.** List `scratchpad/` for a workspace on the same
   topic — a peer's, or an earlier pass. Join it when it exists; one activity has
   one shared workspace. Otherwise create the directory the spec names. Publish
   the material that collaboration or handoff needs; local working material
   keeps its own environment (`general/spec/scratchpad-workspaces`).
2. **Write `index.md` first**, before any other file, with these sections:
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
   - **Stated by the human** — the human's words, verbatim or near-verbatim,
     dated. Nothing an agent inferred goes here; relayed direction is carried as
     said, never reframed (`general/policy/human-contract`).
   - **Derived by agents** — conclusions agents reached, with the file that holds
     each. These are open to challenge; the stated section outranks them.
   - **Decisions** — date, decision, and who agreed, by session id or name. A
     decision is settled only when every active participant agreed
     (`general/principle/attunement`).
   - **Withdrawn** — conclusions retracted, by whom, and why, so no later agent
     re-proposes them.
   - **Open** — unresolved questions, with an owner when one is known.
   - **Promoted** — where agreed material landed: snippet ids, commit SHAs, todo
     slugs, published artifact URLs.
   - **Related** — relative paths to earlier workspaces this one builds on.
3. **Keep the index true as you go.** Update it in the same turn as the change it
   records: a file added or superseded, a decision, a participant joining, a
   promotion. A session that ends abruptly then leaves a true index behind.
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

A minimal index skeleton:

```markdown
# <Topic> — index

Status: active

## Purpose

## Grounding

## Participants

| Session | Agent / model / mode | Role |
| ------- | -------------------- | ---- |

## Files

| File | Purpose | Status |
| ---- | ------- | ------ |

## Stated by the human

## Derived by agents

## Decisions

| Date | Decision | Agreed by |
| ---- | -------- | --------- |

## Withdrawn

## Open

## Promoted

## Related
```

## Outputs

- One workspace directory under the project's `scratchpad/` whose `index.md`
  describes every file in it and reflects the activity's current state.

## Recovery

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

Keep shared material reachable and its index true. The participants who need
to inspect or resume it can identify its authors, current files, settled
decisions and open work through the workspace. Apply this procedure to that
shared material under `general/spec/scratchpad-workspaces`.
