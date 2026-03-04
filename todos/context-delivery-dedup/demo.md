# Demo: context-delivery-dedup

## Validation

```bash
# Before: dependencies expanded inline (duplicate tokens)
# After: dependencies listed as IDs only
telec docs get general/policy/context-retrieval
# Expected: content for context-retrieval only
# Header shows: # Required reads (not loaded): <dep-ids>
# NO dependency content expanded inline
```

```bash
# Explicit fetch of a required read still returns full content
telec docs get general/policy/autonomy
# Expected: full content for autonomy
```

```bash
# Verify AGENTS.md trimming
wc -c ~/.claude/CLAUDE.md
# Expected: under 28000 chars (was ~46000)
```

```bash
# Verify Agent Direct Conversation is on-demand, not baseline
grep -c "Agent Direct Conversation" ~/.claude/CLAUDE.md
# Expected: 0
telec docs get general/procedure/agent-direct-conversation | head -5
# Expected: full snippet content loads on demand
```

## Guided Presentation

### Step 1: Show the dedup behavior

Call `telec docs get` with a snippet that has required reads. Observe that the output
contains ONLY the requested snippet content. The header lists required reads as IDs
without loading them. Point out the token savings — no duplicate content across calls.

### Step 2: Show explicit fetch still works

Call `telec docs get` with one of the listed required read IDs. Full content is returned.
The agent controls what enters its context — the dedup engine is the agent itself.

### Step 3: Show the AGENTS.md reduction

Compare the before/after size of `~/.claude/CLAUDE.md`. Show that Agent Direct Conversation
is gone from the baseline but still available on-demand via `telec docs get`. Show that
the telec CLI spec is trimmed to overview + docs only. Show that the baseline index
is a runtime instruction instead of a pre-loaded list.

### Step 4: End-to-end session simulation

Simulate a multi-call session: first call gets snippet-a (requires c). Second call gets
snippet-b (also requires c). In the old world, c was delivered twice. In the new world,
the agent sees c listed both times in the header but only fetches it once — when it
decides it needs it.
