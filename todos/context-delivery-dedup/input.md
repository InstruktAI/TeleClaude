# context-delivery-dedup — Input

# Context Delivery Deduplication

## Problem

`telec docs get` auto-expands required reads (dependencies) inline. When an agent calls it multiple times in a session, overlapping dependencies get re-delivered — wasting context tokens. The `_resolve_requires()` function in `teleclaude/context_selector.py:422-468` creates a fresh `seen` set per invocation. No cross-call dedup exists.

Example waste: snippet-a requires snippet-c, snippet-b requires snippet-c. Call 1 gets a+c. Call 2 gets b+c again. Later call gets f which also requires c — third copy of c in context.

## Solution

Change the default behavior of `telec docs get`: **list required reads as IDs in the output header, but do NOT expand them inline.** The agent sees the dependency list, checks its own context (which is always the accurate source of truth for "what do I already know"), and fetches only the deps it doesn't have yet.

### Current behavior

```
$ telec docs get snippet-a snippet-b
# PHASE 2: Selected snippet content
# Requested: snippet-a, snippet-b
# Auto-included (required by the above): snippet-c, snippet-d

---
[snippet-c full content]
---
[snippet-d full content]
---
[snippet-a full content]
---
[snippet-b full content]
```

### Target behavior

```
$ telec docs get snippet-a snippet-b
# PHASE 2: Selected snippet content
# Requested: snippet-a, snippet-b
# Required reads (not loaded): snippet-c, snippet-d

---
[snippet-a full content]
---
[snippet-b full content]
```

Agent then calls `telec docs get snippet-c snippet-d` if it needs them. On subsequent calls, if snippet-f also requires snippet-c, the agent sees "Required reads: snippet-c, snippet-e" and only fetches snippet-e because it already has snippet-c.

### No flags needed

This is a default behavior change, not a flag. The agent is the dedup engine — it has perfect knowledge of its own context window. Any mechanism that tries to track loaded state outside the agent (session cache, exclude lists, manifests) creates a second source of truth that will drift.

### Backward compatibility note

The `--baseline-only` flag on `telec docs index` and any existing scripts that parse the "Auto-included" header line will need updating. The header format changes from `# Auto-included (required by the above): ...` to `# Required reads (not loaded): ...`.

## Files to change

1. **`teleclaude/context_selector.py`** — `build_context_output()` at lines 713-768 and `_resolve_requires()` at lines 422-468. Change: still resolve the dependency tree to get the ID list, but don't include dependency content in the output. Only include the requested snippet content. Emit the dep IDs in the header line with the new format.

2. **`teleclaude/cli/telec.py`** — `_handle_docs_get()` at lines 1611-1645. May need minor changes if the output formatting is done here rather than in context_selector.

3. **Tests** — Update any tests that assert on the "Auto-included" output format.

4. **Doc snippets** — Update `general/policy/context-retrieval` and `general/spec/tools/telec-cli` to reflect the new two-call flow: "index first, then get IDs, then get required reads you don't already have."

5. **AGENTS.md baseline instructions** — The Context Retrieval Policy currently says "Use the two-phase flow: index first, then selected snippet IDs." This becomes a three-phase flow: index → get snippets → get missing deps. Update the policy wording. Note: AGENTS.md is generated, so update the source doc snippet, not the generated file.

## Design rationale

- Agent context window is the only accurate source of truth for "what do I already know"
- Extra tool call per batch (1-2 seconds) is trivial compared to thousands of duplicate tokens
- No session state, no caching infrastructure, no flags to learn
- Works identically for first call and tenth call in a session
- Works across agent restarts (agent re-reads context, knows what survived compression)

## Also address while here (AGENTS.md trimming)

While updating context delivery, also implement these AGENTS.md size reductions (current: 47.3k chars, target: <35k):

1. **Move Agent Direct Conversation procedure to on-demand snippet** — 7.8k chars. Only relevant during peer sessions. Already exists as `general/procedure/agent-direct-conversation` in the doc index. Remove from the global AGENTS.md source (`agents/AGENTS.global.md` or wherever it's authored). Agents load it via `telec docs get` when establishing direct links.

2. **Trim Telec CLI spec to overview + docs expanded only** — Currently 14k chars with overview block + expanded sections for docs, sessions, sessions send. Keep overview block (lines 283-346, ~3.5k) and `telec docs` expanded section (~800 chars). Remove `telec sessions`, `telec sessions send` expanded sections. Agents use `telec sessions -h` at runtime. This is done in `docs/global/general/spec/tools/telec-cli.md` — remove the `<!-- @exec: telec sessions -h -->` and `<!-- @exec: telec sessions send -h -->` directives. Note: computers/projects/agents/channels were already removed in this session.

3. **Replace Baseline Index with one-liner** — Currently 2.4k chars listing 16 snippet IDs. Replace with: "Run `telec docs index --baseline-only` before any task where context might be needed." The index is discoverable at runtime.

Expected result: AGENTS.md drops from 47.3k to ~27.5k chars, well under the 40k warning threshold, with room for future growth.
