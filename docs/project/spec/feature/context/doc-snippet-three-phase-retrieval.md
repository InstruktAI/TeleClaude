---
id: 'project/spec/feature/context/doc-snippet-three-phase-retrieval'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Three-phase doc retrieval: telec docs index lists IDs (phase 1), telec docs get returns content (phase 2), and Required-reads dependencies are surfaced for an explicit follow-up fetch (phase 3).'
---

# Doc Snippet Three-Phase Retrieval — Spec

## Required reads

- @docs/project/spec/domain/context.md
- @docs/project/spec/feature/context/doc-selection-policy.md

## What it is

The Index is exposed to agents and operators through a three-phase
retrieval flow:

1. **Phase 1 — discover.** `telec docs index` returns curated metadata
   (IDs, descriptions, status prefixes) so the caller can pick what to
   load.
2. **Phase 2 — fetch.** `telec docs get <id> [<id>...]` returns full
   content for the chosen IDs, with a `# Required reads (not loaded)`
   header listing dependency IDs the body referenced.
3. **Phase 3 — follow up explicitly.** Required reads are NEVER
   auto-loaded. To pull a dependency, the caller re-runs `telec docs
get` against the listed dependency IDs. The explicit follow-up keeps
   the caller in deliberate control of its context budget.

Role gating runs at phases 1 and 2 against the terminal session's
resolved identity; the same gate applies to any phase-3 follow-up fetch.

## Canonical fields

### Use cases

```
Given a logged-in operator with the default terminal role
When they run telec docs index --areas policy --domains software-development
Then phase 1 returns matching snippet metadata sorted by scope then ID
And each entry shows its ID and one-line description
And snippets with status: target render with prefix [target → slug1,slug2]
And snippets with status: mixed render with prefix [mixed → slug]
And snippets with status: actual render with no prefix
```

```
Given a known snippet ID returned by phase 1
When the caller runs telec docs get <id>
Then full Source content is returned with frontmatter stripped
And a "# Required reads (not loaded)" header lists dependency IDs for explicit follow-up
And no Required reads are auto-fetched
```

```
Given an empty argument list
When the caller runs telec docs get
Then the command fails with "At least one snippet ID is required"
```

```
Given an unknown snippet ID
When the caller runs telec docs get unknown/id
Then stdout includes "ERROR: Unknown snippet IDs: unknown/id"
And no content body is returned for that ID
```

```
Given a snippet whose visibility excludes the caller's role
When the caller runs telec docs get on that ID
Then the snippet is surfaced in the output with an "Insufficient role" / "access: denied" notice
And the content body is withheld
```

```
Given a third-party snippet ID
When the caller runs telec docs get on that ID
Then the content body is returned
And Required reads resolution is NOT applied to that ID
```

### Implementation pointers (v1)

- `teleclaude/cli/telec/surface.py:401-422` — `docs index` and `docs get` CLI verb definitions
- `teleclaude/cli/telec/handlers/docs.py:46-107` — `_handle_docs_index` phase 1 handler
- `teleclaude/cli/telec/handlers/docs.py:110-145` — `_handle_docs_get` phase 2 handler
- `teleclaude/cli/telec/handlers/docs.py:19-23` — `_current_terminal_role()` role resolution
- `teleclaude/context_selector.py:674-714` — phase 1 listing build + `_status_prefix`
- `teleclaude/context_selector.py:752-997` — `build_context_output()` main orchestrator
- `teleclaude/context_selector.py:898` — unknown-ID error rendering
- `teleclaude/context_selector.py:925` — required-reads "not loaded" marker emission
- `teleclaude/context_selector.py:984-995` — denied-snippet rendering

### Cross-context references

- **identity** — `_current_terminal_role()` calls `get_identity_resolver().resolve_by_email()` against the terminal-session login to determine the active role; that role drives visibility gating in both phases.
- **selection** — both verbs delegate filter composition (areas, domains, baseline, target) to the Selection policy in `context_selector.py`.

## Known caveats

- Required reads are NEVER auto-loaded. The caller must re-run `telec docs get`
  with the listed dependency IDs if they want the content. This is deliberate
  — the agent controls its context budget — but new agents routinely miss the
  follow-up step on first contact.
- Denied IDs are surfaced rather than hidden. An anonymous caller can confirm
  the existence of an `internal` snippet even though they cannot read it. This
  leaks identity information by design (so callers know to request a role
  lift) but is a real disclosure surface.
- Phase 1 third-party output ignores `--baseline-only` and `--target` filters
  entirely; third-party listings render on a separate track.
- The v1 CLI namespace is `telec docs *`. The v2 target is `telec context
docs *`. The verb rename is a known migration cleanup.
