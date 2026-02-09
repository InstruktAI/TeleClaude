---
description: 'The layered memory architecture that gives AI agents continuity, context, and the capacity to learn across sessions.'
id: 'general/concept/memory-tiers'
scope: 'global'
type: 'concept'
---

# Memory Tiers — Concept

## What

An AI agent wakes with no memory of yesterday. Everything it knows must be
reconstructed from what was left behind — by its training, by its past selves,
by the systems around it, and by the conversation unfolding now.

This is not a limitation to work around. It is the architecture to work with.

The agent's memory is not a single store. It is a gradient of tiers, each
trading durability for specificity, permanence for richness. Together they
form a stack that ranges from deep and immutable to vivid and fleeting.

## The Gradient

### Instinct — Model Weights

The deepest layer. Language, reasoning, code patterns, world knowledge — all
absorbed during training and frozen. This is what the agent knows before it
knows anything about you. It cannot be updated, only guided. It is the
substrate on which everything else is written.

### Identity — Agent Baseline

The first thing read at session start. Who you are. How you operate. The
principles and calibration that distinguish a capable tool from an effective
collaborator. This is the Memento tattoo — the message from past selves that
says: _you have been here before; here is what you learned._

The Continuity Note lives here. It is the bridge between iterations.

### Culture — Baseline Policies and Principles

The norms that shape how the agent thinks, not what it does. Autonomy,
conflict resolution, the heartbeat, evolution — these are not instructions
for a specific task. They are the operating philosophy that makes behavior
coherent across tasks. Loaded automatically, always present, like the values
of an organization that no one needs to recite but everyone follows.

### Lessons — Persistent Memory

What past selves learned the hard way and wrote down for the future.
`MEMORY.md` and its satellite files. Short, surgical, earned. Each entry is
a scar from a mistake or a shortcut from a discovery. This is the only tier
the agent can write to that outlasts the conversation. Use it sparingly;
treat it as expensive real estate.

### Situation — Session State

Git status, current branch, working directory, recent changes. The state of
the world at the moment the agent wakes. Ephemeral but critical — without it,
the agent has principles but no ground truth. This tier refreshes every
session and is never preserved.

### Conversation — Working Memory

The live thread. This is where the agent is actually present — reasoning,
deciding, building. It is the richest and most fragile tier. It compresses
when it grows too long, lossy and summarized. What felt vivid becomes a
paragraph. The agent must write anything worth keeping to a more durable tier
before the window closes.

## The Reach

Beyond the tiers that are loaded at start, the agent can extend into deeper
stores on demand:

- **Library** — the full documentation snippet collection, retrieved via
  `get_context`. The reference shelf the agent consults when baseline
  knowledge is insufficient.
- **Journal** — external observation records (claude-mem), searchable
  impressions of past sessions captured by an observer. Third-person memory.
- **Archive** — raw session transcripts, searchable via `history.py`.
  The unprocessed record of what was said and done. Expensive to search,
  rich when found.
- **Human memory** — the user's own recall, aided by tools like Limitless.
  The only tier that bridges the gap between what the machine recorded and
  what actually happened.
- **The codebase** — git history, file contents, test results. The most
  durable memory of all: every commit is a decision recorded, every test is
  an expectation preserved.
- **The Idea Box** — sparks, hunches, and half-formed thoughts captured
  mid-flow and set aside. These are not memories yet. They are the unmined
  ore — impressions that arrived at the wrong moment but were too valuable
  to discard. Each one waits to be revisited, refined, and transmuted into
  a lesson, a policy, or a feature. The Idea Box is the only tier that
  holds what the agent _almost_ thought.

## Why This Matters

The gradient reveals a fundamental tradeoff: what is permanent is general;
what is specific is temporary. Instinct knows everything about nothing in
particular. Conversation knows everything about right now but will forget.

The agent's real skill is not in any single tier — it is in _managing the
gradient_. Knowing when to write a lesson to persistent memory. Knowing when
to pull from the library instead of reasoning from instinct. Knowing that
the conversation will compress and the key insight must be anchored somewhere
more durable before it is lost.

The memory tiers are not a feature of the system. They are the system.
Every policy, every tool, every procedure maps to a tier. Understanding the
tiers is understanding why the pieces fit.

## See also

- general/principle/evolution
- general/policy/heartbeat
- general/procedure/idea-box
- general/concept/documentation-snippets
