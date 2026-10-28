---
description: 'Save a memory observation — auto-titled, default-project-scoped, identity-tagged, and slotted into a per-project manual session.'
visibility: 'public'
---

# Observation Save — Spec

## What it is

The save path is how a single memory observation enters durable storage, through `telec memories save` or the memory API. The caller supplies a `text` body plus optional `title`, `type`, `project`, and identity scope. The save path resolves project scoping (falling back to `teleclaude` when none is supplied), derives a title from the text when none is given, ensures a per-project manual session exists, and persists the observation. The persisted observation is identified by an id assigned at save and returned to the caller alongside its resolved title and project.

An agent saves an observation when the human it works for asks it to remember something; otherwise a person's memories are kept through curation (`local/projects/teleclaude/spec/feature/memory/memory-curation`). Every agent role reaches the command's capability, `memories-save`, and no role composes it into its explicit set, so it appears in complete help and never in a role's role help (`local/projects/teleclaude/spec/feature/presentation/cli-help`).

## Canonical fields

### Use cases

#### Save an observation for later reference

```gherkin
Given a person asks their agent to remember a statement
When the agent saves it as an observation
Then the observation is stored
And the result identifies it by id, resolved title, and project
```

### Cross-context references

- `identity` — supplies the identity scope honored at save (see `identity-key-ownership`); see `docs/local/spec/domain/identity.md`.
- `agent_runtime` — the session-start consumer does NOT save observations; it only reads them via the context-injection path. See `docs/local/spec/domain/agent_runtime.md` and `memory-context-injection`.

## Known caveats

- **No event emitted on save.** The save path produces no `memory.observation.saved` event. Consumers wanting to react to new observations must poll.
- **No author principal recorded.** Identity is recorded via the looser identity-scope mechanism (see `identity-key-ownership`); a first-class `author_principal` field is a memory-domain cutover decision.
- **Stored body field vs. domain naming.** The text body is persisted under a different field name than the memory domain spec's target naming; reconciling the two is a memory-domain decision.
- **The CLI does NOT expose an identity-scope option.** Only programmatic callers and the in-process context-injection path can supply or read identity scope. CLI-saved observations are always unscoped.
- **Integer id, not UUID.** Observations are identified by an integer id assigned at save. The memory domain spec calls for a UUID observation identifier; promoting to UUID is a cutover decision.

- **No update path on the save surface.** The save path never modifies a persisted observation. A memory's statement is changed, and a memory retired, only through curation (`local/projects/teleclaude/spec/feature/memory/memory-curation`); the other mutations are delete (see `observation-delete`) and search-index re-indexing.
